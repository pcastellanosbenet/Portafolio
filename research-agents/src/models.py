"""Domain models shared by graph nodes, tools and evaluation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceKind = Literal["web", "arxiv", "wikipedia", "other"]
Confidence = Literal["low", "medium", "high"]
Verdict = Literal["approve", "revise"]
Status = Literal[
    "planning",
    "researching",
    "analyzing",
    "reviewing",
    "awaiting_approval",
    "writing",
    "done",
    "failed",
]
RouteName = Literal["planner", "researcher", "analyst", "critic", "writer", "finish"]


def stable_id(prefix: str, text: str) -> str:
    """Build a short deterministic identifier from text."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def utc_now() -> datetime:
    return datetime.now(UTC)


class Usage(BaseModel):
    """Cumulative resource usage for a run."""

    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    search_calls: int = 0
    latency_s: float = 0.0
    models: dict[str, int] = Field(default_factory=dict)

    def merged(self, other: Usage | None) -> Usage:
        if other is None:
            return self.model_copy(deep=True)
        models = dict(self.models)
        for model, calls in other.models.items():
            models[model] = models.get(model, 0) + calls
        return Usage(
            llm_calls=self.llm_calls + other.llm_calls,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            search_calls=self.search_calls + other.search_calls,
            latency_s=round(self.latency_s + other.latency_s, 3),
            models=models,
        )


class Source(BaseModel):
    """A source that can be cited in a note or report."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    url: str
    title: str
    kind: SourceKind = "web"
    snippet: str = ""
    accessed_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, str] = Field(default_factory=dict)


class Claim(BaseModel):
    """One verifiable assertion and the sources that support it."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    text: str
    source_ids: list[str] = Field(default_factory=list)


class Note(BaseModel):
    """Research output for one subquestion."""

    model_config = ConfigDict(extra="forbid")

    note_id: str
    subquestion: str
    summary: str
    claims: list[Claim] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"


class ResearchBrief(BaseModel):
    """The user question after intake."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3)
    language: str = "es"
    constraints: list[str] = Field(default_factory=list)


class SubQuestion(BaseModel):
    """One decomposed research question."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3)
    rationale: str = ""
    source_hints: list[str] = Field(default_factory=list)


class ResearchPlan(BaseModel):
    """Plan produced by the planner node."""

    model_config = ConfigDict(extra="forbid")

    subquestions: list[SubQuestion] = Field(min_length=1, max_length=4)
    search_strategy: str = ""


class Route(BaseModel):
    """Supervisor routing decision."""

    model_config = ConfigDict(extra="forbid")

    next: RouteName
    reason: str


class EvidenceItem(BaseModel):
    """One claim in the analyst's evidence table."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim: str
    source_ids: list[str] = Field(default_factory=list)
    supported: bool | None = None


class Analysis(BaseModel):
    """Analyst's evidence table and coverage assessment."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class Critique(BaseModel):
    """Critic's verdict over the gathered evidence."""

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    supported_claim_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    unsupported_claim_ids: list[str] = Field(default_factory=list)
    missing_source_ids: list[str] = Field(default_factory=list)
    instructions: str = ""


class ResearchOutput(BaseModel):
    """Structured result returned by a researcher backend."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    claims: list[Claim] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"

    def to_note(self, subquestion: str) -> Note:
        source_ids = {source.source_id for source in self.sources}
        for claim in self.claims:
            source_ids.update(claim.source_ids)
        return Note(
            note_id=stable_id("note", subquestion),
            subquestion=subquestion,
            summary=self.summary,
            claims=self.claims,
            source_ids=sorted(source_ids),
            gaps=self.gaps,
            confidence=self.confidence,
        )


class ResearchTask(BaseModel):
    """Input for one researcher invocation."""

    model_config = ConfigDict(extra="forbid")

    subquestion: SubQuestion
    brief: ResearchBrief


class ResearchAnswer(BaseModel):
    """Compact final answer from a tool-using researcher.

    Source metadata is intentionally omitted: it is reconstructed from the
    actual tool payloads, which prevents the model from inventing URLs.
    """

    model_config = ConfigDict(extra="forbid")

    summary: str
    claims: list[Claim] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"


class ReportDraft(BaseModel):
    """Writer output before sources and usage are attached."""

    model_config = ConfigDict(extra="forbid")

    title: str
    answer_markdown: str
    confidence: Confidence = "medium"
    limitations: list[str] = Field(default_factory=list)


class FinalReport(BaseModel):
    """Report returned to the user."""

    model_config = ConfigDict(extra="forbid")

    title: str
    answer_markdown: str
    claims: list[Claim] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    confidence: Confidence = "medium"
    limitations: list[str] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
