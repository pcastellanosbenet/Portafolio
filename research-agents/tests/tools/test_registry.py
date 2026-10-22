"""Tests for backend routing and runtime wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cache import SQLiteCache
from src.config import Settings
from src.services import build_services
from src.tavily_budget import TavilyBudget
from src.tools.base import SearchError, SearchResult
from src.tools.registry import SearchRouter, build_registry


class FakeBackend:
    def __init__(self, name: str, results: list[SearchResult] | None = None) -> None:
        self.name = name
        self.results = results

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        del query, max_results
        if self.results is None:
            raise SearchError("failed")
        return self.results


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        llm_model="test",
        groq_api_key="gsk-test",
        tavily_api_key="tvly-test",
        db_path=tmp_path / "research.db",
    )


def test_search_router_uses_fallback_after_primary_failure() -> None:
    result = SearchResult(
        source_id="src_0123456789ab",
        title="Fallback",
        url="https://example.com/fallback",
    )
    primary = FakeBackend("primary", None)  # type: ignore[arg-type]
    fallback = FakeBackend("fallback", [result])
    router = SearchRouter(primary, fallback)
    assert router.search("query") == [result]


def test_registry_exposes_expected_tools(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    registry = build_registry(
        settings,
        cache=SQLiteCache(tmp_path / "cache.db"),
        tavily_budget=TavilyBudget(tmp_path / "usage.db"),
        ddg_search_fn=lambda query, limit: [],
    )
    assert {tool.name for tool in registry.tools} == {
        "search_web",
        "search_arxiv",
        "search_wikipedia",
        "fetch_page",
    }


def test_build_services_wires_the_tool_researcher(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    services = build_services(settings)
    assert services.researcher.__class__.__name__ == "ToolResearcherBackend"
    assert services.settings.db_path == tmp_path / "research.db"


def test_registry_raises_for_missing_frozen_corpus(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        llm_model="test",
        groq_api_key="gsk-test",
        search_backend="frozen",
        frozen_corpus_path=tmp_path / "missing.json",
    )
    with pytest.raises(SearchError, match="Frozen corpus not found"):
        build_registry(
            settings,
            cache=SQLiteCache(tmp_path / "cache.db"),
            tavily_budget=TavilyBudget(tmp_path / "usage.db"),
        )
