"""Tests for citation validation and tool-source sanitization."""

from __future__ import annotations

import json

from langchain_core.messages import ToolMessage

from src.citations import (
    collect_sources_from_messages,
    normalize_citations,
    sanitize_research_output,
    validate_citations,
)
from src.models import Claim, FinalReport, ResearchOutput, Source

VALID_ID = "src_0123456789ab"
UNKNOWN_ID = "src_ffffffffffff"


def make_source(source_id: str = VALID_ID) -> Source:
    return Source(source_id=source_id, url="https://example.com", title="Example")


def test_valid_report_has_no_citation_issues() -> None:
    report = FinalReport(
        title="Report",
        answer_markdown=f"A claim [{VALID_ID}].",
        claims=[Claim(claim_id="c1", text="A claim", source_ids=[VALID_ID])],
        sources=[make_source()],
    )
    validation = validate_citations(report)
    assert validation.valid
    assert validation.issues == []


def test_normalize_citations_handles_fullwidth_and_brackets() -> None:
    markdown = f"A 【{VALID_ID}】, B [[{VALID_ID}]], C [^{VALID_ID}]."
    normalized = normalize_citations(markdown)
    assert normalized.count(f"[{VALID_ID}]") == 3
    assert "【" not in normalized
    assert "[[" not in normalized


def test_claim_without_sources_is_an_issue() -> None:
    report = FinalReport(
        title="Report",
        answer_markdown="A claim.",
        claims=[Claim(claim_id="c1", text="A claim", source_ids=[])],
        sources=[],
    )
    assert "has no sources" in validate_citations(report).issues[0]


def test_unknown_claim_source_is_an_issue() -> None:
    report = FinalReport(
        title="Report",
        answer_markdown=f"A claim [{UNKNOWN_ID}].",
        claims=[Claim(claim_id="c1", text="A claim", source_ids=[UNKNOWN_ID])],
        sources=[make_source()],
    )
    validation = validate_citations(report)
    assert not validation.valid
    assert UNKNOWN_ID in validation.unknown_source_ids


def test_unknown_markdown_reference_is_an_issue() -> None:
    report = FinalReport(
        title="Report",
        answer_markdown=f"A claim [{UNKNOWN_ID}].",
        claims=[],
        sources=[make_source()],
    )
    assert any("not in the source list" in issue for issue in validate_citations(report).issues)


def test_sanitize_removes_unretrieved_citations() -> None:
    output = ResearchOutput(
        summary="Summary",
        claims=[
            Claim(claim_id="valid", text="Valid", source_ids=[VALID_ID]),
            Claim(claim_id="fake", text="Fake", source_ids=[UNKNOWN_ID]),
            Claim(claim_id="none", text="None", source_ids=[]),
        ],
        sources=[make_source(), make_source(UNKNOWN_ID)],
    )
    sanitized = sanitize_research_output(output, {VALID_ID: make_source()})
    assert [source.source_id for source in sanitized.sources] == [VALID_ID]
    assert [claim.claim_id for claim in sanitized.claims] == ["valid"]
    assert sanitized.claims[0].source_ids == [VALID_ID]
    assert any("not retrieved" in gap for gap in sanitized.gaps)
    assert sanitized.confidence == "low"


def test_sanitize_discards_everything_when_no_tool_sources_exist() -> None:
    output = ResearchOutput(
        summary="Unsupported summary",
        claims=[Claim(claim_id="c1", text="Fake", source_ids=[UNKNOWN_ID])],
        sources=[make_source(UNKNOWN_ID)],
        confidence="high",
    )
    sanitized = sanitize_research_output(output, {})
    assert sanitized.claims == []
    assert sanitized.sources == []
    assert sanitized.summary == "No sources were retrieved for this subquestion."
    assert sanitized.confidence == "low"


def test_collect_sources_from_tool_messages() -> None:
    payload = [
        {
            "source_id": VALID_ID,
            "url": "https://example.com",
            "title": "Example",
            "kind": "web",
            "snippet": "Snippet",
            "backend": "tavily",
            "score": 0.9,
            "metadata": {"backend": "tavily"},
        }
    ]
    message = ToolMessage(content=json.dumps(payload), tool_call_id="call-1", name="search_web")
    sources = collect_sources_from_messages([message])
    assert sources[VALID_ID].title == "Example"


def test_footnote_source_ids_are_counted_for_validation() -> None:
    report = FinalReport(
        title="Report",
        answer_markdown=f"A claim [^c1].\n\n[^c1]: Fuente {VALID_ID}.",
        claims=[],
        sources=[make_source()],
    )
    assert validate_citations(report).valid


def test_unknown_footnote_source_id_is_an_issue() -> None:
    report = FinalReport(
        title="Report",
        answer_markdown=f"A claim [^c1].\n\n[^c1]: Fuente {UNKNOWN_ID}.",
        claims=[],
        sources=[make_source()],
    )
    validation = validate_citations(report)
    assert not validation.valid
    assert UNKNOWN_ID in validation.unknown_source_ids
