"""Structured trace events appended by every graph node."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class TraceEvent(BaseModel):
    """One auditable event in a run."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    node: str
    event: str
    data: dict[str, Any] = Field(default_factory=dict)


def trace(node: str, event: str, **data: Any) -> TraceEvent:
    return TraceEvent(node=node, event=event, data=data)
