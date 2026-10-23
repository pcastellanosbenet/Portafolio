"""Tests for deterministic citation checks in the critic."""

from __future__ import annotations

from src.agents.critic import enforce_critique, fallback_critique
from src.models import Analysis, Claim, Critique, Note, Source


def make_note(claim: Claim) -> Note:
    return Note(
        note_id="n1",
        subquestion="q",
        summary="s",
        claims=[claim],
        source_ids=claim.source_ids,
    )


def test_valid_claim_keeps_approval() -> None:
    source = Source(source_id="s1", url="https://example.com", title="Source")
    note = make_note(Claim(claim_id="c1", text="Claim", source_ids=["s1"]))
    critique = Critique(verdict="approve")
    result = enforce_critique(critique, [note], {"s1": source})
    assert result.verdict == "approve"
    assert result.supported_claim_ids == ["c1"]


def test_missing_source_forces_revision() -> None:
    note = make_note(Claim(claim_id="c1", text="Claim", source_ids=["missing"]))
    critique = Critique(verdict="approve")
    result = enforce_critique(critique, [note], {})
    assert result.verdict == "revise"
    assert result.supported_claim_ids == []
    assert result.unsupported_claim_ids == ["c1"]
    assert result.missing_source_ids == ["missing"]


def test_claim_without_citations_forces_revision() -> None:
    note = make_note(Claim(claim_id="c1", text="Claim", source_ids=[]))
    result = enforce_critique(Critique(verdict="approve"), [note], {})
    assert result.verdict == "revise"
    assert result.unsupported_claim_ids == ["c1"]


def test_fallback_without_claims_approves_with_a_gap() -> None:
    result = fallback_critique([], {}, Analysis(summary="Empty."))
    assert result.verdict == "approve"
    assert "No supported claims were found." in result.gaps
