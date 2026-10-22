"""Tests for the Wikipedia backend."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from src.cache import SQLiteCache
from src.config import Settings
from src.tools.wikipedia import WikipediaSearchBackend


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_model="test",
        groq_api_key="gsk-test",
        search_max_retries=0,
        wikipedia_lang="es",
    )


@respx.mock
def test_wikipedia_parses_search_and_caches(tmp_path: Path) -> None:
    route = respx.get("https://es.wikipedia.org/w/api.php").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": {
                    "search": [
                        {
                            "title": "Inteligencia artificial",
                            "snippet": "<span>La <b>IA</b> es...</span>",
                        }
                    ]
                }
            },
        )
    )
    backend = WikipediaSearchBackend(
        cache=SQLiteCache(tmp_path / "cache.db"),
        settings=make_settings(),
    )
    first = backend.search("inteligencia artificial")
    second = backend.search("inteligencia artificial")

    assert route.call_count == 1
    assert first[0].title == "Inteligencia artificial"
    assert first[0].kind == "wikipedia"
    assert "La IA es" in first[0].snippet
    assert second[0].metadata["cached"] == "1"
