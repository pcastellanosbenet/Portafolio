"""Tests for state reducers."""

from __future__ import annotations

from src.models import Claim, Note, Source, Usage
from src.state import initial_state, merge_notes, merge_sources, merge_usage


def make_note(note_id: str, summary: str) -> Note:
    return Note(
        note_id=note_id,
        subquestion="q",
        summary=summary,
        claims=[Claim(claim_id="c1", text="claim", source_ids=["s1"])],
        source_ids=["s1"],
    )


def test_merge_notes_keeps_latest_version() -> None:
    merged = merge_notes([make_note("n1", "old")], [make_note("n1", "new")])
    assert len(merged) == 1
    assert merged[0].summary == "new"


def test_merge_sources_keeps_latest_metadata() -> None:
    first = Source(source_id="s1", url="https://example.com", title="Old")
    second = Source(source_id="s1", url="https://example.com", title="New")
    merged = merge_sources({"s1": first}, {"s1": second})
    assert merged["s1"].title == "New"


def test_merge_usage_adds_tokens_and_models() -> None:
    merged = merge_usage(
        Usage(llm_calls=1, total_tokens=10, models={"a": 1}),
        Usage(llm_calls=2, total_tokens=20, models={"a": 1, "b": 2}),
    )
    assert merged.llm_calls == 3
    assert merged.total_tokens == 30
    assert merged.models == {"a": 2, "b": 2}


def test_initial_state_has_empty_collections() -> None:
    from src.models import ResearchBrief

    state = initial_state(ResearchBrief(question="What is tested?"), run_id="run-1")
    assert state["run_id"] == "run-1"
    assert state["notes"] == []
    assert state["sources"] == {}
    assert state["usage"].total_tokens == 0
    assert state["status"] == "planning"
