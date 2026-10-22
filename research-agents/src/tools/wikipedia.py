"""Wikipedia search API backend."""

from __future__ import annotations

import html
import re
import time

import httpx

from src.cache import SQLiteCache
from src.config import Settings
from src.tools.base import SearchError, SearchResult
from src.tools.urls import (
    dedupe_results,
    normalize_query,
    query_cache_key,
    quote_wikipedia_title,
    source_id_for_url,
)

_TAG_RE = re.compile(r"<[^>]+>")


class WikipediaSearchBackend:
    name = "wikipedia"

    def __init__(
        self,
        *,
        cache: SQLiteCache,
        settings: Settings,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache = cache
        self.settings = settings
        self.lang = settings.wikipedia_lang.strip() or "en"
        self._client = client or httpx.Client(
            timeout=settings.http_timeout_s,
            headers={"User-Agent": "multi-agent-research/0.1 (portfolio project)"},
        )

    @property
    def api_url(self) -> str:
        return f"https://{self.lang}.wikipedia.org/w/api.php"

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        query = normalize_query(query)
        if not query:
            raise SearchError("Wikipedia query is empty.")
        limit = max(1, min(max_results, 10))
        cache_key = self.cache.make_key(
            "search:wikipedia",
            {"query": query_cache_key(query), "max_results": limit, "lang": self.lang},
        )
        cached = self.cache.get_json(cache_key)
        if cached is not None:
            return [
                SearchResult.model_validate(item).model_copy(
                    update={"metadata": {**item.get("metadata", {}), "cached": "1"}}
                )
                for item in cached
            ]

        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "format": "json",
            "utf8": 1,
            "srprop": "snippet",
        }
        data = self._get(params)
        results: list[SearchResult] = []
        for item in data.get("query", {}).get("search", [])[:limit]:
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            url = f"https://{self.lang}.wikipedia.org/wiki/{quote_wikipedia_title(title)}"
            snippet = html.unescape(_TAG_RE.sub("", str(item.get("snippet", "")))).strip()
            results.append(
                SearchResult(
                    source_id=source_id_for_url(url),
                    title=title,
                    url=url,
                    snippet=snippet,
                    kind="wikipedia",
                    backend="wikipedia",
                    metadata={"backend": "wikipedia", "language": self.lang},
                )
            )
        results = dedupe_results(results)
        self.cache.set_json(
            cache_key,
            [result.model_dump(mode="json") for result in results],
        )
        return results

    def _get(self, params: dict[str, object]) -> dict[str, object]:
        attempts = self.settings.search_max_retries + 1
        last_error = "unknown error"
        for attempt in range(attempts):
            try:
                response = self._client.get(self.api_url, params=params)
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
                raise SearchError(f"Wikipedia returned HTTP {response.status_code}.")
            try:
                data = response.json()
            except ValueError as exc:
                raise SearchError("Wikipedia returned invalid JSON.") from exc
            if not isinstance(data, dict):
                raise SearchError("Wikipedia returned an unexpected payload.")
            return data
        raise SearchError(f"Wikipedia request failed after {attempts} attempt(s): {last_error}.")
