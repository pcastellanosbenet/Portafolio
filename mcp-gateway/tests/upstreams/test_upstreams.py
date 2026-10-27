"""Tests for the bundled upstream servers."""

from __future__ import annotations

import pytest

from src.upstreams.docs.corpus import DocsCorpus
from src.upstreams.ops.state import OpsState
from src.upstreams.research.sources import (
    FixtureSource,
    ResearchService,
    validate_url,
)


def test_docs_corpus_search_and_metadata() -> None:
    corpus = DocsCorpus()
    assert len(corpus.documents) == 5
    results = corpus.search("MRTR aprobación")
    assert results[0]["doc_id"] == "protocolo"
    assert results[0]["score"] > 0
    assert corpus.search("SSRF")[0]["doc_id"] == "seguridad"


def test_docs_corpus_read_outline_and_cite() -> None:
    corpus = DocsCorpus()
    document = corpus.read("seguridad")
    assert "SSRF" in document.content
    assert document.sha256
    assert corpus.outline("seguridad")[0] == {
        "level": 1,
        "text": "Seguridad en servidores MCP",
    }
    assert corpus.cite("seguridad")["citation"].startswith("Seguridad en servidores MCP")
    with pytest.raises(KeyError, match="unknown document"):
        corpus.read("missing")


def test_ops_state_reads_and_writes() -> None:
    state = OpsState()
    assert len(state.list_services()) == 5
    assert len(state.list_incidents("open")) == 3
    metrics = state.query_metrics("api", 8)
    assert len(metrics["points"]) == 8
    assert state.query_metrics("api", 8) == metrics

    incident = state.create_incident("Nuevo", "worker", "sev2")
    assert incident["id"] == "INC-007"
    assert state.ack_incident("INC-007")["status"] == "acknowledged"
    assert state.update_incident("INC-007", "resolved")["status"] == "resolved"

    restarted = state.restart_service("api")
    assert restarted["generation"] == 2
    assert state.delete_namespace("demo")["status"] == "deleted"


def test_ops_state_rejects_unknown_targets() -> None:
    state = OpsState()
    with pytest.raises(ValueError, match="unknown service"):
        state.get_service("missing")
    with pytest.raises(ValueError, match="unknown incident"):
        state.get_incident("INC-999")
    with pytest.raises(ValueError, match="unknown namespace"):
        state.delete_namespace("missing")


async def test_research_fixtures_are_deterministic() -> None:
    service = ResearchService("fixtures")
    first = await service.wikipedia_search("SSRF seguridad", 3)
    second = await service.wikipedia_search("SSRF seguridad", 3)
    assert first == second
    assert first["results"][0]["id"] == "ssrf"
    paper = await service.arxiv_get("2602.00002")
    assert paper["id"] == "2602.00002"
    assert paper["mode"] == "fixtures"


async def test_research_fixture_unknown_page() -> None:
    source = FixtureSource()
    with pytest.raises(ValueError, match="unknown wikipedia page"):
        await source.wikipedia_get("does-not-exist")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost/",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://example.com/",
    ],
)
def test_ssrf_validation_blocks_non_public_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_url(url)


def test_ssrf_validation_allows_public_ip_literal() -> None:
    assert validate_url("https://1.1.1.1/") == "https://1.1.1.1/"
