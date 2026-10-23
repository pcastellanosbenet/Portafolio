"""HITL and checkpoint resume tests."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel

from src.agents.base import AgentServices
from src.budget import BudgetGuard
from src.checkpoint import (
    open_async_checkpointer,
    resume_research,
    resume_research_async,
    run_research_async,
)
from src.config import Settings
from src.graph import build_graph, run_research
from src.llm import InvocationMetadata
from src.models import (
    Analysis,
    Critique,
    EvidenceItem,
    ReportDraft,
    ResearchBrief,
    ResearchPlan,
    SubQuestion,
)
from tests.fakes import FakeLLM, StubResearcher


def make_services(settings: Settings, responses: dict) -> AgentServices:
    return AgentServices(
        llm=FakeLLM(responses),
        researcher=StubResearcher(),
        settings=settings,
        budget=BudgetGuard(settings),
    )


def base_responses() -> dict:
    return {
        ResearchPlan: ResearchPlan(
            subquestions=[SubQuestion(question="What is the evidence?", rationale="Test")]
        ),
        Analysis: Analysis(
            summary="One supported claim.",
            evidence=[
                EvidenceItem(
                    claim_id="claim_1",
                    claim="A supported claim.",
                    source_ids=["src_1"],
                    supported=True,
                )
            ],
        ),
        Critique: Critique(verdict="approve"),
        ReportDraft: ReportDraft(
            title="Test report",
            answer_markdown="A supported claim. [src_1]",
            confidence="high",
        ),
    }


@pytest.mark.asyncio
async def test_hitl_approval_resumes_with_async_sqlite(
    settings: Settings,
    tmp_path,
) -> None:
    hitl_settings = settings.model_copy(update={"hitl": True})
    services = make_services(hitl_settings, base_responses())
    async with open_async_checkpointer(tmp_path / "checkpoints.db") as saver:
        graph = build_graph(services, checkpointer=saver)
        paused = await run_research_async(
            graph,
            ResearchBrief(question="What is the evidence?"),
            run_id="hitl-approve",
            thread_id="hitl-approve",
        )

        assert paused["status"] == "awaiting_approval"
        assert paused["report"] is None
        assert paused["notes"]
        assert paused["__interrupt__"]

        resumed = await resume_research_async(
            graph,
            thread_id="hitl-approve",
            decision={"approved": True, "feedback": "Looks good."},
        )

    assert resumed["status"] == "done"
    assert resumed["hitl"] == {"approved": True, "feedback": "Looks good."}
    assert resumed["report"] is not None
    assert resumed["report"].answer_markdown == "A supported claim. [src_1]"
    assert any(event.event == "hitl_decision" for event in resumed["trace"])


@pytest.mark.asyncio
async def test_hitl_rejection_stops_without_writing(
    settings: Settings,
    tmp_path,
) -> None:
    hitl_settings = settings.model_copy(update={"hitl": True})
    services = make_services(hitl_settings, base_responses())
    async with open_async_checkpointer(tmp_path / "checkpoints.db") as saver:
        graph = build_graph(services, checkpointer=saver)
        paused = await run_research_async(
            graph,
            ResearchBrief(question="What is the evidence?"),
            run_id="hitl-reject",
            thread_id="hitl-reject",
        )
        assert paused["status"] == "awaiting_approval"

        resumed = await resume_research_async(
            graph,
            thread_id="hitl-reject",
            decision={"approved": False, "feedback": "Faltan fuentes primarias."},
        )

    assert resumed["status"] == "failed"
    assert resumed["report"] is None
    assert resumed["hitl"] == {
        "approved": False,
        "feedback": "Faltan fuentes primarias.",
    }
    assert any("Faltan fuentes primarias" in error for error in resumed["errors"])


class CrashOnceLLM(FakeLLM):
    """Crash once in the writer to exercise checkpoint retry."""

    def __init__(self, responses: dict) -> None:
        super().__init__(responses)
        self.crashed = False

    def invoke_structured[T: BaseModel](
        self,
        schema: type[T],
        messages: Sequence[BaseMessage],
        *,
        fast: bool = False,
    ) -> tuple[T, InvocationMetadata]:
        if schema is ReportDraft and not self.crashed:
            self.crashed = True
            raise KeyboardInterrupt("simulated process death")
        return super().invoke_structured(schema, messages, fast=fast)


def test_resume_after_simulated_crash_keeps_state(settings: Settings) -> None:
    services = AgentServices(
        llm=CrashOnceLLM(base_responses()),
        researcher=StubResearcher(),
        settings=settings,
        budget=BudgetGuard(settings),
    )
    graph = build_graph(services, checkpointer=MemorySaver())

    with pytest.raises(KeyboardInterrupt):
        run_research(
            graph,
            ResearchBrief(question="What is the evidence?"),
            run_id="crash-1",
            thread_id="crash-1",
        )

    checkpoint = graph.get_state({"configurable": {"thread_id": "crash-1"}})
    assert checkpoint.next == ("writer",)
    assert checkpoint.values["notes"]

    resumed = resume_research(
        graph,
        thread_id="crash-1",
        decision=None,
    )

    assert resumed["status"] == "done"
    assert resumed["report"] is not None
    assert resumed["report"].answer_markdown == "A supported claim. [src_1]"
