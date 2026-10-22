"""Tests for page fetching, redirects and SSRF protection."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from src.cache import SQLiteCache
from src.config import Settings
from src.tools.base import FetchError, UnsafeURLError
from src.tools.fetch import HttpPageFetcher

HTML = """<html><head><title>Example title</title></head>
<body><article><p>Hello world from a test page.</p></article></body></html>"""


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_model="test",
        groq_api_key="gsk-test",
        fetch_max_chars=5000,
    )


def public_resolver(host: str, port: int) -> list[str]:
    return ["93.184.216.34"]


def test_fetch_extracts_text_and_caches(tmp_path: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=HTML,
        )

    fetcher = HttpPageFetcher(
        cache=SQLiteCache(tmp_path / "cache.db"),
        settings=make_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        resolver=public_resolver,
    )
    first = fetcher.fetch("https://example.com/page")
    second = fetcher.fetch("https://example.com/page")

    assert len(calls) == 1
    assert "Hello world" in first.text
    assert not first.cached
    assert second.cached


def test_fetch_follows_safe_redirect(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=HTML,
        )

    fetcher = HttpPageFetcher(
        cache=SQLiteCache(tmp_path / "cache.db"),
        settings=make_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        resolver=public_resolver,
    )
    page = fetcher.fetch("https://example.com/start")
    assert page.final_url == "https://example.com/final"


def test_fetch_rejects_private_url_before_request(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("private URL should not be requested")

    fetcher = HttpPageFetcher(
        cache=SQLiteCache(tmp_path / "cache.db"),
        settings=make_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        resolver=public_resolver,
    )
    with pytest.raises(UnsafeURLError):
        fetcher.fetch("http://127.0.0.1/admin")


def test_fetch_rejects_redirect_to_private_url(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

    fetcher = HttpPageFetcher(
        cache=SQLiteCache(tmp_path / "cache.db"),
        settings=make_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        resolver=public_resolver,
    )
    with pytest.raises(UnsafeURLError):
        fetcher.fetch("https://example.com/start")


def test_fetch_rejects_unsupported_content_type(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF",
        )

    fetcher = HttpPageFetcher(
        cache=SQLiteCache(tmp_path / "cache.db"),
        settings=make_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        resolver=public_resolver,
    )
    with pytest.raises(FetchError, match="Unsupported content type"):
        fetcher.fetch("https://example.com/file.pdf")
