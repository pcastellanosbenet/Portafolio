"""Graph state and reducers."""

from __future__ import annotations

import operator
import uuid
from typing import Annotated, TypedDict

from src.models import (
    Analysis,
    Critique,
    FinalReport,
    Note,
    ResearchBrief,
    ResearchPlan,
    Route,
    Source,
    Status,
    Usage,
)
from src.trace import TraceEvent


def merge_notes(left: list[Note], right: list[Note]) -> list[Note]:
    """Merge notes by id, keeping the latest version of each note."""
    merged = {note.note_id: note for note in left}
    for note in right:
        merged[note.note_id] = note
    return list(merged.values())


def merge_sources(left: dict[str, Source], right: dict[str, Source]) -> dict[str, Source]:
    """Merge source dictionaries, keeping the latest metadata."""
    merged = dict(left)
    merged.update(right)
    return merged


def merge_usage(left: Usage, right: Usage) -> Usage:
    return left.merged(right)


class ResearchState(TypedDict, total=False):
    """Shared blackboard for the research team."""

    run_id: str
    brief: ResearchBrief
    plan: ResearchPlan | None
    notes: Annotated[list[Note], merge_notes]
    sources: Annotated[dict[str, Source], merge_sources]
    analysis: Analysis | None
    critique: Critique | None
    report: FinalReport | None
    route: Route | None
    round: int
    usage: Annotated[Usage, merge_usage]
    trace: Annotated[list[TraceEvent], operator.add]
    status: Status
    errors: Annotated[list[str], operator.add]


def initial_state(brief: ResearchBrief, *, run_id: str | None = None) -> ResearchState:
    return ResearchState(
        run_id=run_id or uuid.uuid4().hex,
        brief=brief,
        plan=None,
        notes=[],
        sources={},
        analysis=None,
        critique=None,
        report=None,
        route=None,
        round=0,
        usage=Usage(),
        trace=[],
        status="planning",
        errors=[],
    )
