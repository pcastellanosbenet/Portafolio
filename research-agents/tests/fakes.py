"""Deterministic fakes for graph tests."""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel

from src.agents.base import ResearchResult
from src.llm import InvocationMetadata
from src.models import Claim, ResearchOutput, ResearchTask, Source, Usage


class FakeLLM:
    """Return scripted structured responses for each schema."""

    def __init__(self, responses: dict[type[BaseModel], BaseModel | list[BaseModel]]) -> None:
        self.responses: dict[type[BaseModel], list[BaseModel]] = {}
        for schema, value in responses.items():
            self.responses[schema] = list(value) if isinstance(value, list) else [value]
        self.calls: list[type[BaseModel]] = []

    def invoke_structured[T: BaseModel](
        self,
        schema: type[T],
        messages: Sequence[BaseMessage],
        *,
        fast: bool = False,
    ) -> tuple[T, InvocationMetadata]:
        self.calls.append(schema)
        queue = self.responses.get(schema)
        if not queue:
            raise AssertionError(f"No fake response configured for {schema.__name__}")
        value = queue.pop(0) if len(queue) > 1 else queue[0]
        if not isinstance(value, schema):
            raise AssertionError(f"Fake response for {schema.__name__} has the wrong type")
        return value, InvocationMetadata(
            provider="fake",
            model="fake-model",
            method="json_schema",
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )

    def invoke_text(
        self,
        messages: Sequence[BaseMessage],
        *,
        fast: bool = False,
    ) -> AIMessage:
        return AIMessage(content="fake text response")


class StubResearcher:
    """Return predefined research outputs for each subquestion."""

    def __init__(self, outputs: list[ResearchOutput] | None = None) -> None:
        self.outputs = list(outputs or [])
        self.calls: list[ResearchTask] = []

    def research(self, task: ResearchTask, *, max_steps: int = 3) -> ResearchResult:
        self.calls.append(task)
        if self.outputs:
            output = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        else:
            output = default_output(task)
        return ResearchResult(
            output=output,
            usage=Usage(llm_calls=1, total_tokens=100, models={"fake-researcher": 1}),
        )


def make_source(source_id: str = "src_1", *, snippet: str = "Example evidence.") -> Source:
    return Source(
        source_id=source_id,
        url=f"https://example.com/{source_id}",
        title=f"Source {source_id}",
        snippet=snippet,
    )


def make_claim(
    claim_id: str = "claim_1",
    *,
    text: str = "A supported claim.",
    source_ids: list[str] | None = None,
) -> Claim:
    return Claim(
        claim_id=claim_id,
        text=text,
        source_ids=["src_1"] if source_ids is None else source_ids,
    )


def make_output(
    task: ResearchTask | None,
    *,
    claims: list[Claim] | None = None,
    sources: list[Source] | None = None,
    gaps: list[str] | None = None,
) -> ResearchOutput:
    source = make_source()
    summary = (
        f"Evidence for: {task.subquestion.question}" if task is not None else "Evidence summary."
    )
    return ResearchOutput(
        summary=summary,
        claims=[make_claim()] if claims is None else claims,
        sources=[source] if sources is None else sources,
        gaps=gaps or [],
        confidence="medium",
    )


def default_output(task: ResearchTask) -> ResearchOutput:
    return make_output(task)
