"""Tool factory and LangChain tool registry."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_core.tools import BaseTool, tool

from src.cache import SQLiteCache
from src.config import Settings
from src.tavily_budget import TavilyBudget
from src.tools.arxiv_search import ArxivSearchBackend
from src.tools.base import (
    FetchedPage,
    FetchError,
    SearchBackend,
    SearchError,
    SearchResult,
)
from src.tools.duckduckgo import DuckDuckGoSearchBackend
from src.tools.fetch import HttpPageFetcher
from src.tools.frozen import FrozenSearchBackend
from src.tools.tavily import TavilySearchBackend
from src.tools.wikipedia import WikipediaSearchBackend

logger = logging.getLogger(__name__)


class SearchRouter:
    """Try the primary backend and fall back on recoverable failures."""

    name = "router"

    def __init__(
        self,
        primary: SearchBackend,
        fallback: SearchBackend | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        errors: list[str] = []
        try:
            results = self.primary.search(query, max_results=max_results)
            if results:
                return results
            errors.append(f"{self.primary.name}: no results")
        except SearchError as exc:
            errors.append(f"{self.primary.name}: {exc}")
            logger.warning("Primary search backend failed: %s", exc)

        if self.fallback is not None:
            try:
                results = self.fallback.search(query, max_results=max_results)
                if results:
                    logger.info("Using fallback search backend %s.", self.fallback.name)
                    return results
                errors.append(f"{self.fallback.name}: no results")
            except SearchError as exc:
                errors.append(f"{self.fallback.name}: {exc}")
                logger.warning("Fallback search backend failed: %s", exc)
        raise SearchError("; ".join(errors) or "No search backend returned results.")


@dataclass(frozen=True)
class ToolRegistry:
    tools: list[BaseTool]
    search: SearchRouter
    arxiv: ArxivSearchBackend
    wikipedia: WikipediaSearchBackend
    fetcher: HttpPageFetcher


def _search_payload(results: list[SearchResult]) -> str:
    payload = []
    for result in results:
        item = result.model_dump(mode="json")
        if len(item.get("snippet", "")) > 1_000:
            item["snippet"] = item["snippet"][:1_000] + "…"
        payload.append(item)
    return json.dumps(payload, ensure_ascii=False)


def _page_payload(page: FetchedPage) -> str:
    return json.dumps(page.model_dump(mode="json"), ensure_ascii=False)


def _build_primary(
    settings: Settings,
    *,
    cache: SQLiteCache,
    tavily_budget: TavilyBudget,
    http_client: httpx.Client,
    ddg_search_fn: Callable[[str, int], list[dict[str, Any]]] | None,
) -> SearchBackend:
    backend_name = "frozen" if settings.search_backend == "frozen" else settings.search_primary
    if backend_name == "frozen":
        return FrozenSearchBackend(settings.frozen_corpus_path)
    if backend_name == "tavily":
        has_key = (
            settings.tavily_api_key is not None
            and settings.tavily_api_key.get_secret_value().strip()
        )
        if not has_key:
            logger.warning("TAVILY_API_KEY is missing; using DuckDuckGo as primary search.")
            return DuckDuckGoSearchBackend(cache=cache, search_fn=ddg_search_fn)
        return TavilySearchBackend(
            settings.tavily_api_key,
            cache=cache,
            budget=tavily_budget,
            settings=settings,
            client=http_client,
        )
    return DuckDuckGoSearchBackend(cache=cache, search_fn=ddg_search_fn)


def _build_fallback(
    settings: Settings,
    *,
    cache: SQLiteCache,
    primary: SearchBackend,
    ddg_search_fn: Callable[[str, int], list[dict[str, Any]]] | None,
) -> SearchBackend | None:
    if settings.search_fallback == "none" or primary.name == "duckduckgo":
        return None
    if settings.search_fallback == "duckduckgo":
        return DuckDuckGoSearchBackend(cache=cache, search_fn=ddg_search_fn)
    return None


def build_registry(
    settings: Settings,
    *,
    cache: SQLiteCache,
    tavily_budget: TavilyBudget,
    http_client: httpx.Client | None = None,
    ddg_search_fn: Callable[[str, int], list[dict[str, Any]]] | None = None,
) -> ToolRegistry:
    """Build search, page and domain tools from configuration."""
    client = http_client or httpx.Client(
        timeout=settings.http_timeout_s,
        follow_redirects=False,
        headers={"User-Agent": "multi-agent-research/0.1 (portfolio project)"},
    )
    primary = _build_primary(
        settings,
        cache=cache,
        tavily_budget=tavily_budget,
        http_client=client,
        ddg_search_fn=ddg_search_fn,
    )
    fallback = _build_fallback(
        settings,
        cache=cache,
        primary=primary,
        ddg_search_fn=ddg_search_fn,
    )
    router = SearchRouter(primary, fallback)
    arxiv = ArxivSearchBackend(cache=cache, settings=settings, client=client)
    wikipedia = WikipediaSearchBackend(cache=cache, settings=settings, client=client)
    fetcher = HttpPageFetcher(cache=cache, settings=settings, client=client)

    def _limit(value: int) -> int:
        return max(1, min(value, settings.search_max_results))

    @tool
    def search_web(query: str, max_results: int = 5) -> str:
        """Search the web for recent or general information.

        Returns JSON with source_id, title, url, snippet and kind. Use the
        source_id values in claim citations.
        """
        results = router.search(query, max_results=_limit(max_results))
        return _search_payload(results)

    @tool
    def search_arxiv(query: str, max_results: int = 5) -> str:
        """Search arXiv for scientific papers and preprints."""
        results = arxiv.search(query, max_results=_limit(max_results))
        return _search_payload(results)

    @tool
    def search_wikipedia(query: str, max_results: int = 5) -> str:
        """Search Wikipedia for encyclopedic background and definitions."""
        results = wikipedia.search(query, max_results=_limit(max_results))
        return _search_payload(results)

    @tool
    def fetch_page(url: str) -> str:
        """Fetch a public page and return its extracted readable text.

        Use this after a search when the snippet is not enough. The response
        includes the source_id and final URL for citation.
        """
        try:
            page = fetcher.fetch(url)
        except FetchError as exc:
            return json.dumps({"error": str(exc), "url": url}, ensure_ascii=False)
        return _page_payload(page)

    return ToolRegistry(
        tools=[search_web, search_arxiv, search_wikipedia, fetch_page],
        search=router,
        arxiv=arxiv,
        wikipedia=wikipedia,
        fetcher=fetcher,
    )
