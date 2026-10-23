"""End-to-end graph tests with deterministic fakes."""

from __future__ import annotations

import pytest
from langgraph.errors import GraphRecursionError

from src.agents.base import AgentServices, ResearcherBackend
from src.agents.researcher import SingleShotResearcherBackend
from src.budget import BudgetGuard
from src.config import Settings
from src.graph import build_graph, run_research
from src.models import (
    Analysis,
    Critique,
    EvidenceItem,
    ReportDraft,
    ResearchBrief,
    ResearchOutput,
    ResearchPlan,
    Route,
    SubQuestion,
)
from tests.fakes import FakeLLM, StubResearcher, make_claim, make_output, make_source


def make_services(
    settings: Settings,
    responses: dict,
    researcher: ResearcherBackend | None = None,
) -> AgentServices:
    llm = FakeLLM(responses)
    return AgentServices(
        llm=llm,
        researcher=researcher or StubResearcher(),
        settings=settings,
        budget=BudgetGuard(settings),
    )


def base_responses() -> dict:
    return {
        ResearchPlan: ResearchPlan(
            subquestions=[
                SubQuestion(question="What evidence supports the claim?", rationale="Test")
            ]
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


def test_happy_path_produces_report(settings: Settings) -> None:
    services = make_services(settings, base_responses())
    graph = build_graph(services)
    state = run_research(graph, ResearchBrief(question="What is the evidence?"))

    assert state["status"] == "done"
    assert state["report"] is not None
    assert state["report"].answer_markdown == "A supported claim. [src_1]"
    assert len(state["report"].claims) == 1
    assert state["report"].sources[0].source_id == "src_1"
    assert state["route"] is not None
    assert state["route"].next == "finish"
    assert state["usage"].llm_calls == 5
    assert state["usage"].total_tokens == 160
    assert state["report"].usage.total_tokens == 160
    nodes = {event.node for event in state["trace"]}
    assert {"planner", "researcher", "analyst", "critic", "writer", "supervisor"} <= nodes


def test_parallel_research_dispatches_one_worker_per_subquestion(settings: Settings) -> None:
    responses = base_responses()
    responses[ResearchPlan] = ResearchPlan(
        subquestions=[
            SubQuestion(question="First subquestion?", rationale="Test"),
            SubQuestion(question="Second subquestion?", rationale="Test"),
        ]
    )
    researcher = StubResearcher()
    services = make_services(settings, responses, researcher)
    state = run_research(build_graph(services), ResearchBrief(question="What is the evidence?"))

    assert state["status"] == "done"
    assert len(researcher.calls) == 2
    assert {call.subquestion.question for call in researcher.calls} == {
        "First subquestion?",
        "Second subquestion?",
    }
    assert len(state["notes"]) == 2
    assert state["report"] is not None


def test_max_concurrency_does_not_skip_subquestions(settings: Settings) -> None:
    responses = base_responses()
    responses[ResearchPlan] = ResearchPlan(
        subquestions=[
            SubQuestion(question=f"Subquestion {index}?", rationale="Test")
            for index in range(3)
        ]
    )
    researcher = StubResearcher()
    services = make_services(settings, responses, researcher)
    state = run_research(
        build_graph(services),
        ResearchBrief(question="What is the evidence?"),
        max_concurrency=2,
    )

    assert state["status"] == "done"
    assert len(researcher.calls) == 3
    assert len(state["notes"]) == 3
    assert state["report"] is not None


def test_critic_revision_runs_a_second_round(settings: Settings) -> None:
    unsupported = make_output(
        task=None,
        claims=[make_claim(source_ids=[])],
        sources=[],
        gaps=["No source for the first claim."],
    )
    supported = make_output(
        task=None,
        claims=[make_claim()],
        sources=[make_source()],
    )
    researcher = StubResearcher(outputs=[unsupported, supported])
    responses = base_responses()
    responses[Critique] = [Critique(verdict="approve"), Critique(verdict="approve")]
    responses[Analysis] = [
        Analysis(
            summary="Unsupported claim.",
            evidence=[
                EvidenceItem(claim_id="claim_1", claim="A supported claim.", supported=False)
            ],
        ),
        Analysis(
            summary="Supported claim.",
            evidence=[
                EvidenceItem(
                    claim_id="claim_1",
                    claim="A supported claim.",
                    source_ids=["src_1"],
                    supported=True,
                )
            ],
        ),
    ]
    responses[Route] = Route(next="researcher", reason="The first claim lacks evidence.")
    services = make_services(settings, responses, researcher)
    state = run_research(build_graph(services), ResearchBrief(question="What is the evidence?"))

    assert state["status"] == "done"
    assert state["round"] == 2
    assert len(researcher.calls) == 2
    assert state["report"] is not None
    assert state["report"].claims[0].source_ids == ["src_1"]


def test_round_limit_stops_revision_after_the_configured_number(
    settings: Settings,
) -> None:
    limited = settings.model_copy(update={"max_rounds": 1})
    responses = base_responses()
    responses[Critique] = Critique(verdict="revise", gaps=["Still missing evidence."])
    researcher = StubResearcher()
    services = make_services(limited, responses, researcher)

    state = run_research(
        build_graph(services),
        ResearchBrief(question="What is the evidence?"),
    )

    assert state["round"] == 1
    assert len(researcher.calls) == 1
    assert state["report"] is not None
    assert any("another research round" in item for item in state["report"].limitations)


def test_trace_events_have_the_expected_schema(settings: Settings) -> None:
    services = make_services(settings, base_responses())
    state = run_research(build_graph(services), ResearchBrief(question="What is the evidence?"))

    for event in state["trace"]:
        payload = event.model_dump(mode="json")
        assert {"timestamp", "node", "event", "data"} <= payload.keys()
        assert isinstance(payload["node"], str)
        assert isinstance(payload["event"], str)

    assert any("tokens" in event.data for event in state["trace"])
    assert any("latency_s" in event.data for event in state["trace"])
    assert any("llm_calls" in event.data for event in state["trace"])


def test_budget_exhaustion_still_returns_a_report(settings: Settings) -> None:
    exhausted = settings.model_copy(update={"max_llm_calls": 0})
    services = make_services(exhausted, {})
    state = run_research(
        build_graph(services),
        ResearchBrief(question="What happens without a budget?"),
    )

    assert state["status"] == "done"
    assert state["report"] is not None
    assert state["report"].confidence == "low"
    assert state["report"].limitations
    assert "No research notes were collected." in state["report"].limitations


def test_unanswerable_question_reports_insufficient_evidence(settings: Settings) -> None:
    empty = ResearchOutput(
        summary="No evidence was found.",
        claims=[],
        sources=[],
        gaps=["No sources matched the question."],
        confidence="low",
    )
    responses = base_responses()
    responses[ReportDraft] = ReportDraft(
        title="Insufficient evidence",
        answer_markdown="The available evidence was insufficient.",
        confidence="low",
        limitations=["No sources matched the question."],
    )
    services = make_services(settings, responses, StubResearcher(outputs=[empty]))
    state = run_research(build_graph(services), ResearchBrief(question="An unanswerable question?"))

    assert state["status"] == "done"
    assert state["report"] is not None
    assert state["report"].confidence == "low"
    assert "insufficient" in state["report"].answer_markdown.lower()
    assert any("No sources matched" in limitation for limitation in state["report"].limitations)


def test_single_shot_backend_uses_the_structured_schema(settings: Settings) -> None:
    from src.models import ResearchTask

    output = make_output(task=None)
    llm = FakeLLM({ResearchOutput: output})
    backend = SingleShotResearcherBackend(llm)
    task = ResearchTask(
        subquestion=SubQuestion(question="What is tested?"),
        brief=ResearchBrief(question="What is tested?"),
    )
    result = backend.research(task)
    assert result.output.claims[0].claim_id == "claim_1"
    assert result.usage.llm_calls == 1


def test_recursion_limit_is_a_hard_stop(settings: Settings) -> None:
    services = make_services(settings, base_responses())

    with pytest.raises(GraphRecursionError):
        run_research(
            build_graph(services),
            ResearchBrief(question="What is the evidence?"),
            recursion_limit=1,
        )
