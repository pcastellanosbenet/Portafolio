"""Tests for the B0/B1/B2 evaluation runners with deterministic fakes."""

from __future__ import annotations

from typing import Any

from src.agents.base import AgentServices, ResearcherBackend
from src.budget import BudgetGuard
from src.config import Settings
from src.eval.systems import run_b0, run_b1, run_b2
from src.models import (
    FinalReport,
    ReportDraft,
    ResearchPlan,
    ResearchTask,
    SubQuestion,
    Usage,
)
from tests.fakes import FakeLLM, StubResearcher, make_output


def make_services(
    settings: Settings,
    responses: dict[Any, Any],
    researcher: ResearcherBackend | None = None,
) -> AgentServices:
    return AgentServices(
        llm=FakeLLM(responses),
        researcher=researcher or StubResearcher(),
        settings=settings,
        budget=BudgetGuard(settings),
    )


def make_plan(count: int = 1) -> ResearchPlan:
    return ResearchPlan(
        subquestions=[
            SubQuestion(question=f"Subquestion {index}?", rationale="Test")
            for index in range(count)
        ]
    )


def test_b0_uses_one_researcher_and_builds_a_citable_report(settings: Settings) -> None:
    output = make_output(None)
    researcher = StubResearcher(outputs=[output])
    services = make_services(settings, {}, researcher)

    result = run_b0(services, "What is the evidence?", run_id="b0-test")

    assert result.status == "done"
    assert result.report is not None
    assert result.report.claims == output.claims
    assert result.report.sources == output.sources
    assert result.usage.total_tokens == 100
    assert len(researcher.calls) == 1


def test_b1_runs_planner_researchers_and_writer_without_full_team(
    settings: Settings,
) -> None:
    responses = {
        ResearchPlan: make_plan(2),
        ReportDraft: ReportDraft(
            title="Informe",
            answer_markdown="A supported claim. [src_1]",
            confidence="high",
        ),
    }
    researcher = StubResearcher()
    services = make_services(settings, responses, researcher)

    result = run_b1(services, "What is the evidence?", run_id="b1-test")

    assert result.status == "done"
    assert result.report is not None
    assert result.report.answer_markdown == "A supported claim. [src_1]"
    assert len(researcher.calls) == 2
    assert services.llm.calls == [ResearchPlan, ReportDraft]
    assert result.usage.llm_calls == 4
    assert result.usage.total_tokens == 230


def test_b1_survives_planner_and_writer_failures(settings: Settings) -> None:
    class FailingLLM(FakeLLM):
        def invoke_structured(self, schema, messages, *, fast=False):  # type: ignore[no-untyped-def]
            raise RuntimeError("provider down")

    services = AgentServices(
        llm=FailingLLM({}),
        researcher=StubResearcher(),
        settings=settings,
        budget=BudgetGuard(settings),
    )

    result = run_b1(services, "What is the evidence?", run_id="b1-failure")

    assert result.status == "done"
    assert result.report is not None
    assert result.errors
    assert result.report.limitations


def test_b2_delegates_to_the_full_graph(settings: Settings) -> None:
    class FakeGraph:
        def invoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            del config
            report = FinalReport(
                title="Full graph",
                answer_markdown="Graph answer.",
                usage=Usage(llm_calls=4, total_tokens=80),
            )
            return {
                **state,
                "status": "done",
                "report": report,
                "usage": Usage(llm_calls=4, total_tokens=80),
                "trace": [],
                "errors": [],
            }

    services = make_services(settings, {}, StubResearcher())
    result = run_b2(services, "What is the evidence?", run_id="b2-test", graph=FakeGraph())

    assert result.status == "done"
    assert result.report is not None
    assert result.report.title == "Full graph"
    assert result.usage.total_tokens == 80


def test_b0_returns_a_failed_run_when_the_researcher_raises(settings: Settings) -> None:
    class FailingResearcher:
        def research(self, task: ResearchTask, *, max_steps: int = 3, usage=None):  # type: ignore[no-untyped-def]
            raise RuntimeError("researcher down")

    services = AgentServices(
        llm=FakeLLM({}),
        researcher=FailingResearcher(),  # type: ignore[arg-type]
        settings=settings,
        budget=BudgetGuard(settings),
    )

    result = run_b0(services, "What is the evidence?", run_id="b0-failure")

    assert result.status == "failed"
    assert result.report is None
    assert "researcher down" in result.errors[0]
