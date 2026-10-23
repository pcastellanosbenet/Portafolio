"""Parallel research dispatcher, worker and simple researcher backend."""

from __future__ import annotations

import time

from langgraph.types import Command, Send

from src.agents.base import (
    AgentServices,
    ResearcherBackend,
    ResearchResult,
    StructuredLLM,
    json_payload,
)
from src.budget import usage_from_metadata
from src.models import ResearchOutput, ResearchTask, SubQuestion, Usage
from src.prompts import messages
from src.state import ResearchState
from src.trace import trace


class SingleShotResearcherBackend:
    """LLM-only researcher used for offline dry runs.

    This backend does not retrieve sources, so its output must not be used for
    a real report. Production runs use ``ToolResearcherBackend``.
    """

    def __init__(self, llm: StructuredLLM) -> None:
        self.llm = llm

    def research(
        self,
        task: ResearchTask,
        *,
        max_steps: int = 3,
        usage: Usage | None = None,
    ) -> ResearchResult:
        del usage
        started = time.perf_counter()
        output, metadata = self.llm.invoke_structured(
            ResearchOutput,
            messages(
                "researcher",
                json_payload(
                    {
                        "task": task.model_dump(mode="json"),
                        "max_steps": max_steps,
                    }
                ),
            ),
            fast=True,
        )
        return ResearchResult(
            output=output,
            usage=usage_from_metadata(metadata, latency_s=time.perf_counter() - started),
        )


def make_researcher(services: AgentServices):
    """Dispatch one researcher worker per subquestion."""

    def researcher(state: ResearchState) -> Command:
        plan = state.get("plan")
        if plan is None:
            return Command(
                goto="supervisor",
                update={
                    "errors": ["researcher: no plan available"],
                    "status": "failed",
                    "trace": [trace("researcher", "missing_plan")],
                },
            )

        if not services.budget.can_research(state):
            return Command(
                goto="writer",
                update={
                    "round": state.get("round", 0) + 1,
                    "status": "writing",
                    "errors": ["researcher: budget or round limit reached before dispatch"],
                    "trace": [trace("researcher", "dispatch_skipped_budget")],
                },
            )

        selected = plan.subquestions
        sends = [
            Send(
                "researcher_worker",
                {
                    "brief": state["brief"],
                    "subquestion": subquestion,
                    "usage": state.get("usage", Usage()),
                },
            )
            for subquestion in selected
        ]
        if not sends:
            return Command(
                goto="writer",
                update={
                    "round": state.get("round", 0) + 1,
                    "status": "writing",
                    "errors": ["researcher: plan had no subquestions to dispatch"],
                    "trace": [trace("researcher", "dispatch_empty")],
                },
            )

        return Command(
            goto=sends,
            update={
                "round": state.get("round", 0) + 1,
                "analysis": None,
                "critique": None,
                "status": "researching",
                "errors": [],
                "trace": [
                    trace(
                        "researcher",
                        "dispatch",
                        workers=len(sends),
                        max_workers=services.settings.max_workers,
                        round=state.get("round", 0) + 1,
                    )
                ],
            },
        )

    return researcher


def make_researcher_worker(services: AgentServices):
    """Research exactly one subquestion."""

    def worker(state: ResearchState) -> dict[str, object]:
        brief = state["brief"]
        raw_subquestion = state.get("subquestion")
        if raw_subquestion is None:
            return {
                "errors": ["researcher_worker: missing subquestion"],
                "trace": [trace("researcher_worker", "missing_subquestion")],
            }
        subquestion = (
            raw_subquestion
            if isinstance(raw_subquestion, SubQuestion)
            else SubQuestion.model_validate(raw_subquestion)
        )
        task = ResearchTask(subquestion=subquestion, brief=brief)
        try:
            result = services.researcher.research(
                task,
                max_steps=services.settings.max_tool_steps,
                usage=state.get("usage", Usage()),
            )
        except Exception as exc:  # noqa: BLE001 - one failed worker must not kill the run
            return {
                "errors": [f"researcher_worker: {type(exc).__name__}: {exc}"],
                "trace": [trace("researcher_worker", "failed", subquestion=subquestion.question)],
            }

        note = result.output.to_note(subquestion.question)
        return {
            "notes": [note],
            "sources": {source.source_id: source for source in result.output.sources},
            "usage": result.usage,
            "errors": list(result.errors),
            "trace": [
                *result.trace,
                trace(
                    "researcher_worker",
                    "completed",
                    subquestion=subquestion.question,
                    claims=len(note.claims),
                    sources=len(result.output.sources),
                    tools=result.tools_used,
                    tokens=result.usage.total_tokens,
                    latency_s=result.usage.latency_s,
                    llm_calls=result.usage.llm_calls,
                ),
            ],
        }

    return worker


def build_researcher(
    llm: StructuredLLM,
    backend: ResearcherBackend | None = None,
) -> ResearcherBackend:
    """Return the configured researcher backend."""
    return backend or SingleShotResearcherBackend(llm)
