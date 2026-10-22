"""Frozen search backend for reproducible offline evaluations."""

from __future__ import annotations

import json
from pathlib import Path

from src.tools.base import SearchError, SearchResult
from src.tools.urls import dedupe_results, normalize_query, query_cache_key, source_id_for_url


class FrozenSearchBackend:
    """Read search results from a JSON corpus.

    Expected shape::

        {"queries": {"question": [{"title": "...", "url": "...", "snippet": "..."}]}}
    """

    name = "frozen"

    def __init__(self, path: Path) -> None:
        self.path = path
        if not path.is_file():
            raise SearchError(f"Frozen corpus not found: {path}")
        try:
            self._data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SearchError(f"Could not read frozen corpus {path}: {exc}") from exc
        queries = self._data.get("queries") if isinstance(self._data, dict) else None
        if not isinstance(queries, dict):
            raise SearchError("Frozen corpus must contain a 'queries' object.")

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        key = query_cache_key(normalize_query(query))
        rows = self._data["queries"].get(key)
        if rows is None:
            rows = self._data["queries"].get(normalize_query(query), [])
        results = []
        for row in rows[: max(1, min(max_results, 10))]:
            url = str(row.get("url", "")).strip()
            if not url:
                continue
            results.append(
                SearchResult(
                    source_id=source_id_for_url(url),
                    title=str(row.get("title") or url).strip(),
                    url=url,
                    snippet=str(row.get("snippet") or "").strip(),
                    kind=str(row.get("kind") or "web"),  # type: ignore[arg-type]
                    backend=self.name,
                    metadata={"backend": self.name},
                )
            )
        return dedupe_results(results)
