"""Shared protocols and service container for graph nodes."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel

from src.budget import BudgetGuard
from src.config import Settings
from src.llm import InvocationMetadata
from src.models import ResearchOutput, ResearchTask, Source, Usage
from src.trace import TraceEvent


class StructuredLLM(Protocol):
    """The subset of ``LLMClient`` used by agents and tests."""

    def invoke_structured[T: BaseModel](
        self,
        schema: type[T],
        messages: Sequence[BaseMessage],
        *,
        fast: bool = False,
    ) -> tuple[T, InvocationMetadata]: ...


class ToolLLM(StructuredLLM, Protocol):
    """LLM capable of binding tools for a ReAct researcher."""

    def chat_model(self, *, fast: bool = False) -> BaseChatModel: ...

    def invoke_text(
        self,
        messages: Sequence[BaseMessage],
        *,
        fast: bool = False,
    ) -> AIMessage: ...

    def invoke_with_tools(
        self,
        messages: Sequence[BaseMessage],
        tools: Sequence[Any],
        *,
        fast: bool = False,
    ) -> AIMessage: ...


@dataclass(frozen=True)
class ResearchResult:
    """A researcher output plus the resources it consumed."""

    output: ResearchOutput
    usage: Usage = field(default_factory=Usage)
    tools_used: list[str] = field(default_factory=list)
    trace: list[TraceEvent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ResearcherBackend(Protocol):
    """Pluggable researcher used by the parallel research worker."""

    def research(
        self,
        task: ResearchTask,
        *,
        max_steps: int = 3,
        usage: Usage | None = None,
    ) -> ResearchResult: ...


@dataclass(frozen=True)
class AgentServices:
    """Dependencies injected into every node."""

    llm: StructuredLLM
    researcher: ResearcherBackend
    settings: Settings
    budget: BudgetGuard


def json_payload(value: Any) -> str:
    """Serialize Pydantic models and nested values for prompts."""

    def default(item: Any) -> Any:
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        return str(item)

    return json.dumps(value, ensure_ascii=False, indent=2, default=default)


def compact_sources(
    sources: Sequence[Source],
    *,
    snippet_chars: int = 220,
) -> list[dict[str, str]]:
    """Keep the citation fields and a short snippet to fit free-tier TPM limits."""
    return [
        {
            "source_id": source.source_id,
            "title": source.title,
            "url": source.url,
            "kind": source.kind,
            "snippet": source.snippet[:snippet_chars],
        }
        for source in sources
    ]


def compact_notes(
    notes: Sequence[Any],
    *,
    summary_chars: int = 400,
    max_gaps: int = 5,
) -> list[dict[str, Any]]:
    """Keep claims and identifiers while trimming prose for verifier calls."""
    payload: list[dict[str, Any]] = []
    for note in notes:
        payload.append(
            {
                "subquestion": note.subquestion,
                "summary": note.summary[:summary_chars],
                "claims": [claim.model_dump(mode="json") for claim in note.claims],
                "gaps": list(note.gaps[:max_gaps]),
                "confidence": note.confidence,
            }
        )
    return payload
