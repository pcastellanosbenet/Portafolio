"""Request and response schemas for the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models import FinalReport, Usage
from src.trace import TraceEvent

RunStatus = Literal[
    "queued",
    "running",
    "awaiting_approval",
    "completed",
    "failed",
    "rejected",
]
HealthStatus = Literal["ok", "degraded"]


class ResearchRequest(BaseModel):
    """Input for a new research run."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=4_000)
    language: str = Field(default="es", min_length=2, max_length=16)
    hitl: bool | None = Field(
        default=None,
        description=(
            "Pause before the writer for human approval. Omit to use the server default."
        ),
    )
    run_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
        description="Optional caller-provided id for idempotency and SSE URLs.",
    )


class ResearchAccepted(BaseModel):
    """Response returned as soon as a run has been scheduled."""

    run_id: str
    thread_id: str
    status: RunStatus
    status_url: str
    events_url: str


class RunView(BaseModel):
    """Current state, trace and result of a research run."""

    run_id: str
    thread_id: str
    question: str
    language: str
    hitl: bool
    status: RunStatus
    graph_status: str
    created_at: datetime
    updated_at: datetime
    interrupt: dict[str, Any] | None = None
    report: FinalReport | None = None
    usage: Usage = Field(default_factory=Usage)
    errors: list[str] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)
    status_url: str
    events_url: str


class ApprovalRequest(BaseModel):
    """Human decision for a run paused before the writer."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    feedback: str = Field(default="", max_length=2_000)


class ApprovalAccepted(BaseModel):
    """Response after a human decision has been queued."""

    run_id: str
    status: RunStatus
    status_url: str


class ProviderHealth(BaseModel):
    """Provider configuration without any secret material."""

    name: str
    model: str
    fast_model: str
    api_key_configured: bool
    fallback_provider: str | None = None
    fallback_api_key_configured: bool = False


class CheckpointerHealth(BaseModel):
    """Checkpointer backend status."""

    backend: str
    status: Literal["ok", "unavailable"]


class HealthResponse(BaseModel):
    """Service health and effective configuration."""

    status: HealthStatus
    version: str
    checkpointer: CheckpointerHealth
    provider: ProviderHealth
    search_backend: str
    active_runs: int
