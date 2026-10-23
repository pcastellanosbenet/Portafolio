"""Pydantic models for the frozen evaluation.

The evaluation data is intentionally explicit: every question carries the
reference facts used by the deterministic coverage metric, the source URLs that
must support the answer, and a short rubric note. The judge only sees these
references and the candidate answer, never the system name.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models import Claim, Source, Usage
from src.trace import TraceEvent

QuestionCategory = Literal["factual", "comparison", "multi_hop", "unanswerable"]
SystemName = Literal["b0", "b1", "b2"]


class ExpectedFact(BaseModel):
    """One reference fact and the surface forms that count as covering it."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    text: str = Field(min_length=3)
    any_of: list[str] = Field(min_length=1)


class EvalQuestion(BaseModel):
    """One evaluation question and its references."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    category: QuestionCategory
    question: str = Field(min_length=10)
    answerable: bool = True
    expected_facts: list[ExpectedFact] = Field(default_factory=list)
    expected_source_urls: list[str] = Field(default_factory=list)
    rubric: str = ""

    @model_validator(mode="after")
    def _validate_references(self) -> EvalQuestion:
        if self.answerable:
            if not self.expected_facts:
                raise ValueError("Answerable questions need at least one expected fact.")
            if not self.expected_source_urls:
                raise ValueError("Answerable questions need at least one expected source URL.")
        elif self.expected_facts or self.expected_source_urls:
            raise ValueError("Unanswerable questions must not declare expected facts or sources.")
        fact_ids = [fact.id for fact in self.expected_facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("Expected fact ids must be unique within a question.")
        if len(self.expected_source_urls) != len(set(self.expected_source_urls)):
            raise ValueError("Expected source URLs must be unique within a question.")
        return self


class QuestionSet(BaseModel):
    """The versioned evaluation question set."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    created_at: date
    description: str = ""
    questions: list[EvalQuestion] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_questions(self) -> QuestionSet:
        ids = [question.id for question in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("Question ids must be unique.")
        categories = {question.category for question in self.questions}
        required = {"factual", "comparison", "multi_hop", "unanswerable"}
        missing = required - categories
        if missing:
            raise ValueError(f"Question set is missing categories: {sorted(missing)}")
        return self


class JudgeOutput(BaseModel):
    """Structured judgment for one answer.

    ``covered_fact_ids`` and ``missing_fact_ids`` refer to the reference fact
    ids in the question. The parser normalizes them before they enter metrics.
    """

    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=2)
    covered_fact_ids: list[str] = Field(default_factory=list)
    missing_fact_ids: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    citation_issues: list[str] = Field(default_factory=list)
    abstained: bool = False
    rationale: str = Field(min_length=1)


class EvaluationRecord(BaseModel):
    """One raw system run plus its deterministic and judged metrics."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    system_run_id: str = ""
    system: SystemName
    question_id: str
    category: QuestionCategory
    question: str
    repetition: int = 1
    answer_markdown: str = ""
    claims: list[Claim] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    confidence: str = "medium"
    status: str = "failed"
    errors: list[str] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    duration_s: float = 0.0
    trace: list[TraceEvent] = Field(default_factory=list)
    judge: JudgeOutput | None = None
    judge_usage: Usage | None = None
    judge_error: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    run_config: dict[str, Any] = Field(default_factory=dict)
