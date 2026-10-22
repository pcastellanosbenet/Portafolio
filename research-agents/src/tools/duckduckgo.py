"""DuckDuckGo fallback backend."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.cache import SQLiteCache
from src.tools.base import SearchError, SearchResult
from src.tools.urls import dedupe_results, normalize_query, query_cache_key, source_id_for_url

SearchFn = Callable[[str, int], list[dict[str, Any]]]


def _default_search(query: str, max_results: int) -> list[dict[str, Any]]:
    from ddgs import DDGS

    with DDGS() as client:
        return list(client.text(query, max_results=max_results))


class DuckDuckGoSearchBackend:
    name = "duckduckgo"

    def __init__(
        self,
        *,
        cache: SQLiteCache,
        search_fn: SearchFn | None = None,
    ) -> None:
        self.cache = cache
        self._search = search_fn or _default_search

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        query = normalize_query(query)
        if not query:
            raise SearchError("DuckDuckGo query is empty.")
        limit = max(1, min(max_results, 10))
        cache_key = self.cache.make_key(
            "search:duckduckgo",
            {"query": query_cache_key(query), "max_results": limit},
        )
        cached = self.cache.get_json(cache_key)
        if cached is not None:
            return [
                SearchResult.model_validate(item).model_copy(
                    update={"metadata": {**item.get("metadata", {}), "cached": "1"}}
                )
                for item in cached
            ]

        try:
            rows = self._search(query, limit)
        except Exception as exc:  # noqa: BLE001 - normalize third-party failures
            raise SearchError(f"DuckDuckGo failed: {type(exc).__name__}: {exc}") from exc

        results: list[SearchResult] = []
        for row in rows[:limit]:
            url = str(row.get("href") or row.get("url") or "").strip()
            if not url:
                continue
            results.append(
                SearchResult(
                    source_id=source_id_for_url(url),
                    title=str(row.get("title") or url).strip(),
                    url=url,
                    snippet=str(row.get("body") or row.get("snippet") or "").strip(),
                    kind="web",
                    backend=self.name,
                    metadata={"backend": self.name},
                )
            )
        results = dedupe_results(results)
        self.cache.set_json(
            cache_key,
            [result.model_dump(mode="json") for result in results],
        )
        return results
