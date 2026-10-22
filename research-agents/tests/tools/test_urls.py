"""Tests for URL canonicalization, deduplication and SSRF checks."""

from __future__ import annotations

import pytest

from src.tools.base import SearchResult, UnsafeURLError
from src.tools.urls import (
    canonicalize_url,
    dedupe_results,
    resolve_redirect,
    source_id_for_url,
    validate_public_url,
)


def test_canonicalize_removes_tracking_fragment_and_default_port() -> None:
    url = "HTTPS://Example.COM:443/path/?utm_source=x&b=2&a=1#section"
    assert canonicalize_url(url) == "https://example.com/path?a=1&b=2"


def test_canonicalize_keeps_root_and_non_default_port() -> None:
    assert canonicalize_url("http://example.com:8080/") == "http://example.com:8080/"


def test_source_id_is_stable_across_equivalent_urls() -> None:
    first = source_id_for_url("https://example.com/a?utm_source=x")
    second = source_id_for_url("https://example.com/a/")
    assert first == second
    assert first.startswith("src_")


def test_dedupe_prefers_longer_snippet_and_merges_metadata() -> None:
    first = SearchResult(
        source_id="old",
        title="Title",
        url="https://example.com/a?utm_source=x",
        snippet="short",
        metadata={"one": "1"},
    )
    second = SearchResult(
        source_id="new",
        title="Title",
        url="https://example.com/a",
        snippet="a much longer snippet",
        metadata={"two": "2"},
    )
    merged = dedupe_results([first, second])
    assert len(merged) == 1
    assert merged[0].snippet == "a much longer snippet"
    assert merged[0].metadata == {"one": "1", "two": "2"}
    assert merged[0].url == "https://example.com/a"


def test_public_url_is_accepted_with_injected_resolver() -> None:
    url = validate_public_url(
        "https://example.com/article",
        resolver=lambda host, port: ["93.184.216.34"],
    )
    assert url == "https://example.com/article"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost/",
        "http://metadata.google.internal/",
        "file:///etc/passwd",
        "https://example.com:8080/",
    ],
)
def test_unsafe_urls_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeURLError):
        validate_public_url(url, resolver=lambda host, port: ["93.184.216.34"])


def test_private_dns_answer_is_rejected() -> None:
    with pytest.raises(UnsafeURLError, match="non-public"):
        validate_public_url(
            "https://example.com/",
            resolver=lambda host, port: ["192.168.1.10"],
        )


def test_redirect_resolution_is_canonical() -> None:
    assert (
        resolve_redirect("https://example.com/a", "/b?utm_source=x")
        == "https://example.com/b"
    )
