"""Shared protocols and service container for graph nodes."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from src.budget import BudgetGuard
from src.config import Settings
from src.llm import InvocationMetadata
from src.models import ResearchOutput, ResearchTask, Usage


class StructuredLLM(Protocol):
    """The subset of ``LLMClient`` used by agents and tests."""

    def invoke_structured[T: BaseModel](
        self,
        schema: type[T],
        messages: Sequence[BaseMessage],
        *,
        fast: bool = False,
    ) -> tuple[T, InvocationMetadata]: ...


@dataclass(frozen=True)
class ResearchResult:
    """A researcher output plus the resources it consumed."""

    output: ResearchOutput
    usage: Usage = field(default_factory=Usage)


class ResearcherBackend(Protocol):
    """Pluggable researcher used by the sequential research node."""

    def research(self, task: ResearchTask, *, max_steps: int = 3) -> ResearchResult: ...


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
