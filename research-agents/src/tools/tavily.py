"""Tavily search backend with cache and monthly quota accounting."""

from __future__ import annotations

import time

import httpx
from pydantic import SecretStr

from src.cache import SQLiteCache
from src.config import Settings
from src.tavily_budget import TavilyBudget
from src.tools.base import SearchError, SearchResult
from src.tools.urls import dedupe_results, normalize_query, query_cache_key, source_id_for_url

TAVILY_URL = "https://api.tavily.com/search"


class TavilySearchBackend:
    name = "tavily"

    def __init__(
        self,
        api_key: SecretStr | str,
        *,
        cache: SQLiteCache,
        budget: TavilyBudget,
        settings: Settings,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        if not self._api_key.strip():
            raise SearchError("TAVILY_API_KEY is not set.")
        self.cache = cache
        self.budget = budget
        self.settings = settings
        self._client = client or httpx.Client(timeout=settings.http_timeout_s)

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        query = normalize_query(query)
        if not query:
            raise SearchError("Tavily query is empty.")
        limit = max(1, min(max_results, 10))
        cache_key = self.cache.make_key(
            "search:tavily",
            {
                "query": query_cache_key(query),
                "max_results": limit,
                "depth": self.settings.tavily_search_depth,
            },
        )
        cached = self.cache.get_json(cache_key)
        if cached is not None:
            return [
                SearchResult.model_validate(item).model_copy(
                    update={"metadata": {**item.get("metadata", {}), "cached": "1"}}
                )
                for item in cached
            ]

        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": limit,
            "search_depth": self.settings.tavily_search_depth,
            "include_answer": False,
            "include_raw_content": False,
        }
        data = self._request(payload)
        results: list[SearchResult] = []
        for item in data.get("results", [])[:limit]:
            url = str(item.get("url", "")).strip()
            title = str(item.get("title", "")).strip() or url
            if not url:
                continue
            metadata = {"backend": self.name}
            published = item.get("published_date")
            if published:
                metadata["published_date"] = str(published)
            results.append(
                SearchResult(
                    source_id=source_id_for_url(url),
                    title=title,
                    url=url,
                    snippet=str(item.get("content", "")).strip(),
                    kind="web",
                    backend=self.name,
                    score=float(item["score"]) if item.get("score") is not None else None,
                    metadata=metadata,
                )
            )
        results = dedupe_results(results)
        self.cache.set_json(
            cache_key,
            [result.model_dump(mode="json") for result in results],
        )
        return results

    def _request(self, payload: dict[str, object]) -> dict[str, object]:
        attempts = self.settings.search_max_retries + 1
        last_error = "unknown error"
        for attempt in range(attempts):
            self.budget.reserve()
            try:
                response = self._client.post(TAVILY_URL, json=payload)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt + 1 < attempts:
                    time.sleep(min(2**attempt, 5))
                    continue
                break
            if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
                last_error = f"HTTP {response.status_code}"
                time.sleep(min(2**attempt, 5))
                continue
            if response.status_code >= 400:
                raise SearchError(f"Tavily returned HTTP {response.status_code}.")
            try:
                data = response.json()
            except ValueError as exc:
                raise SearchError("Tavily returned invalid JSON.") from exc
            if not isinstance(data, dict):
                raise SearchError("Tavily returned an unexpected payload.")
            return data
        raise SearchError(f"Tavily request failed after {attempts} attempt(s): {last_error}.")
