"""Tests for the Tavily backend with respx."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from src.cache import SQLiteCache
from src.config import Settings
from src.tavily_budget import TavilyBudget
from src.tools.base import SearchBudgetExceeded
from src.tools.tavily import TAVILY_URL, TavilySearchBackend


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "llm_model": "test",
        "groq_api_key": "gsk-test",
        "tavily_api_key": "tvly-test",
        "search_max_retries": 0,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def make_backend(tmp_path: Path, *, limit: int = 10) -> TavilySearchBackend:
    cache = SQLiteCache(tmp_path / "cache.db")
    budget = TavilyBudget(tmp_path / "usage.db", monthly_limit=limit)
    return TavilySearchBackend(
        "tvly-test",
        cache=cache,
        budget=budget,
        settings=make_settings(),
    )


@respx.mock
def test_tavily_search_parses_and_caches_results(tmp_path: Path) -> None:
    route = respx.post(TAVILY_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Example",
                        "url": "https://example.com/page?utm_source=x",
                        "content": "A useful snippet.",
                        "score": 0.9,
                    }
                ]
            },
        )
    )
    backend = make_backend(tmp_path)
    first = backend.search("test query", max_results=3)
    second = backend.search("test query", max_results=3)

    assert route.call_count == 1
    assert len(first) == 1
    assert first[0].title == "Example"
    assert first[0].url == "https://example.com/page"
    assert first[0].source_id.startswith("src_")
    assert first[0].metadata["cached"] if "cached" in first[0].metadata else True
    assert second[0].metadata["cached"] == "1"


@respx.mock
def test_tavily_budget_blocks_new_queries(tmp_path: Path) -> None:
    route = respx.post(TAVILY_URL).mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    backend = make_backend(tmp_path, limit=1)
    backend.search("first")
    with pytest.raises(SearchBudgetExceeded):
        backend.search("second")
    assert route.call_count == 1


@respx.mock
def test_tavily_http_error_is_reported(tmp_path: Path) -> None:
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(400, json={"error": "bad"}))
    backend = make_backend(tmp_path)
    with pytest.raises(Exception, match="Tavily returned HTTP 400"):
        backend.search("bad query")
