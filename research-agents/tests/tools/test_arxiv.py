"""Tests for the arXiv backend."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from src.cache import SQLiteCache
from src.config import Settings
from src.tools.arxiv_search import ARXIV_URL, ArxivSearchBackend

ATOM_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <published>2024-01-01T00:00:00Z</published>
    <title>  A Test Paper  </title>
    <summary>  This is the abstract.  </summary>
    <author><name>Ada Lovelace</name></author>
    <link rel="alternate" href="http://arxiv.org/abs/2401.00001v1"/>
  </entry>
</feed>
"""


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_model="test",
        groq_api_key="gsk-test",
        search_max_retries=0,
    )


@respx.mock
def test_arxiv_parses_atom_and_caches(tmp_path: Path) -> None:
    route = respx.get(ARXIV_URL).mock(
        return_value=httpx.Response(200, text=ATOM_RESPONSE)
    )
    backend = ArxivSearchBackend(
        cache=SQLiteCache(tmp_path / "cache.db"),
        settings=make_settings(),
    )
    first = backend.search("test paper")
    second = backend.search("test paper")

    assert route.call_count == 1
    assert len(first) == 1
    assert first[0].title == "A Test Paper"
    assert first[0].kind == "arxiv"
    assert first[0].url.startswith("https://arxiv.org/abs/")
    assert second[0].metadata["cached"] == "1"
