"""Tests for supervisor routing guards."""

from __future__ import annotations

from src.agents.base import AgentServices
from src.agents.supervisor import allowed_routes, make_supervisor
from src.budget import BudgetGuard
from src.config import Settings
from src.models import (
    Analysis,
    Claim,
    Critique,
    FinalReport,
    Note,
    ResearchBrief,
    ResearchPlan,
    Route,
    Source,
    SubQuestion,
)
from src.state import initial_state
from tests.fakes import FakeLLM, StubResearcher


def make_services(settings: Settings, responses: dict) -> AgentServices:
    return AgentServices(
        llm=FakeLLM(responses),
        researcher=StubResearcher(),
        settings=settings,
        budget=BudgetGuard(settings),
    )


def populated_state(settings: Settings) -> dict:
    state = initial_state(ResearchBrief(question="What is tested?"))
    state["plan"] = ResearchPlan(subquestions=[SubQuestion(question="Subquestion?")])
    state["notes"] = [
        Note(
            note_id="n1",
            subquestion="Subquestion?",
            summary="Summary",
            claims=[Claim(claim_id="c1", text="Claim", source_ids=["s1"])],
            source_ids=["s1"],
        )
    ]
    state["sources"] = {"s1": Source(source_id="s1", url="https://example.com", title="S")}
    state["analysis"] = Analysis(summary="One claim.")
    state["critique"] = Critique(verdict="revise")
    state["round"] = 1
    return state


def test_initial_route_is_planner(settings: Settings) -> None:
    services = make_services(settings, {})
    state = initial_state(ResearchBrief(question="What is tested?"))
    assert allowed_routes(state, services) == ["planner"]


def test_revision_allows_research_or_writer(settings: Settings) -> None:
    services = make_services(settings, {})
    assert allowed_routes(populated_state(settings), services) == ["researcher", "writer"]


def test_report_ends_the_run(settings: Settings) -> None:
    services = make_services(settings, {})
    state = initial_state(ResearchBrief(question="What is tested?"))
    state["report"] = FinalReport(title="Done", answer_markdown="Done")
    assert allowed_routes(state, services) == ["finish"]


def test_invalid_llm_route_falls_back_to_allowed_route(settings: Settings) -> None:
    services = make_services(
        settings,
        {Route: Route(next="analyst", reason="Invalid for this state.")},
    )
    supervisor = make_supervisor(services)
    command = supervisor(populated_state(settings))

    assert command.goto == "researcher"
    assert command.update is not None
    assert command.update["route"].next == "researcher"
    assert command.update["errors"]


def test_single_allowed_route_does_not_call_the_model(settings: Settings) -> None:
    fake = FakeLLM({})
    services = AgentServices(
        llm=fake,
        researcher=StubResearcher(),
        settings=settings,
        budget=BudgetGuard(settings),
    )
    supervisor = make_supervisor(services)
    state = initial_state(ResearchBrief(question="What is tested?"))
    command = supervisor(state)

    assert command.goto == "planner"
    assert fake.calls == []
