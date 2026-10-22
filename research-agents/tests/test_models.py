"""Tests for domain model validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models import Claim, ResearchOutput, ResearchPlan, Source, SubQuestion, Usage


def test_plan_requires_at_least_one_subquestion() -> None:
    with pytest.raises(ValidationError):
        ResearchPlan(subquestions=[])


def test_plan_rejects_more_than_four_subquestions() -> None:
    with pytest.raises(ValidationError):
        ResearchPlan(
            subquestions=[SubQuestion(question=f"Question {index}?") for index in range(5)]
        )


def test_source_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Source(
            source_id="s1",
            url="https://example.com",
            title="Source",
            unknown="value",  # type: ignore[call-arg]
        )


def test_research_output_note_collects_source_ids() -> None:
    source = Source(source_id="s1", url="https://example.com", title="Source")
    output = ResearchOutput(
        summary="Summary",
        claims=[Claim(claim_id="c1", text="Claim", source_ids=["s1"])],
        sources=[source],
    )
    note = output.to_note("What is tested?")
    assert note.note_id.startswith("note_")
    assert note.source_ids == ["s1"]
    assert note.claims[0].claim_id == "c1"


def test_usage_merge_preserves_zero_values() -> None:
    merged = Usage().merged(Usage(llm_calls=1, total_tokens=10))
    assert merged.llm_calls == 1
    assert merged.total_tokens == 10
