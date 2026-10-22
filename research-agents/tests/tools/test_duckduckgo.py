"""Tests for the DuckDuckGo fallback backend."""

from __future__ import annotations

from pathlib import Path

from src.cache import SQLiteCache
from src.tools.duckduckgo import DuckDuckGoSearchBackend


def test_duckduckgo_parses_and_caches(tmp_path: Path) -> None:
    calls = []

    def search_fn(query: str, max_results: int) -> list[dict[str, str]]:
        calls.append(query)
        return [
            {
                "title": "DDG result",
                "href": "https://example.com/ddg?utm_medium=x",
                "body": "Snippet from DuckDuckGo.",
            }
        ]

    backend = DuckDuckGoSearchBackend(
        cache=SQLiteCache(tmp_path / "cache.db"),
        search_fn=search_fn,
    )
    first = backend.search("test query")
    second = backend.search("test query")

    assert calls == ["test query"]
    assert first[0].url == "https://example.com/ddg"
    assert first[0].backend == "duckduckgo"
    assert second[0].metadata["cached"] == "1"
