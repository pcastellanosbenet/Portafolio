"""Researcher backend and sequential research node."""

from __future__ import annotations

import time

from src.agents.base import (
    AgentServices,
    ResearcherBackend,
    ResearchResult,
    StructuredLLM,
    json_payload,
)
from src.budget import usage_from_metadata
from src.models import ResearchOutput, ResearchTask, Usage
from src.prompts import messages
from src.state import ResearchState
from src.trace import trace


class SingleShotResearcherBackend:
    """LLM-only researcher used before the tool backend is wired.

    This backend is suitable for graph tests and offline dry runs. It does not
    retrieve web sources, so its output must not be used for a real report.
    Phase 2 replaces it with a tool-using researcher.
    """

    def __init__(self, llm: StructuredLLM) -> None:
        self.llm = llm

    def research(self, task: ResearchTask, *, max_steps: int = 3) -> ResearchResult:
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
    def researcher(state: ResearchState) -> dict[str, object]:
        plan = state.get("plan")
        if plan is None:
            return {
                "errors": ["researcher: no plan available"],
                "status": "failed",
                "trace": [trace("researcher", "missing_plan")],
            }

        notes = []
        sources = {}
        usage = Usage()
        errors: list[str] = []
        completed = 0

        for subquestion in plan.subquestions:
            projected = state.get("usage", Usage()).merged(usage)
            if not services.budget.can_llm({**state, "usage": projected}):
                errors.append(
                    "researcher: budget exhausted before all subquestions were researched"
                )
                break
            task = ResearchTask(subquestion=subquestion, brief=state["brief"])
            try:
                result = services.researcher.research(
                    task,
                    max_steps=services.settings.max_tool_steps,
                )
            except Exception as exc:  # noqa: BLE001 - one failed subquestion must not kill the run
                errors.append(f"researcher: {type(exc).__name__}: {exc}")
                continue
            note = result.output.to_note(subquestion.question)
            notes.append(note)
            sources.update({source.source_id: source for source in result.output.sources})
            usage = usage.merged(result.usage)
            completed += 1

        return {
            "notes": notes,
            "sources": sources,
            "usage": usage,
            "round": state.get("round", 0) + 1,
            "analysis": None,
            "critique": None,
            "status": "researching",
            "errors": errors,
            "trace": [
                trace(
                    "researcher",
                    "research_round",
                    subquestions=len(plan.subquestions),
                    completed=completed,
                    notes=len(notes),
                    sources=len(sources),
                    round=state.get("round", 0) + 1,
                )
            ],
        }

    return researcher


def build_researcher(
    llm: StructuredLLM,
    backend: ResearcherBackend | None = None,
) -> ResearcherBackend:
    """Return the configured researcher backend."""
    return backend or SingleShotResearcherBackend(llm)
