"""API contract tests with a deterministic fake graph."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from app.main import create_app
from app.rate_limit import RateLimiter
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.agents.base import AgentServices
from src.budget import BudgetGuard
from src.config import Settings
from src.graph import build_graph
from src.models import (
    Analysis,
    Claim,
    Critique,
    EvidenceItem,
    FinalReport,
    ReportDraft,
    ResearchPlan,
    Source,
    SubQuestion,
    Usage,
)
from src.trace import TraceEvent
from tests.fakes import FakeLLM, StubResearcher

pytestmark = pytest.mark.asyncio


def make_report(question: str = "What is a transformer?") -> FinalReport:
    source = Source(
        source_id="src_1",
        url="https://example.com/source",
        title="Example source",
        snippet="Short evidence.",
    )
    return FinalReport(
        title="Test report",
        answer_markdown=f"Answer for: {question} [src_1]",
        claims=[Claim(claim_id="claim_1", text="A supported claim.", source_ids=["src_1"])],
        sources=[source],
        confidence="high",
        usage=Usage(llm_calls=2, total_tokens=100),
    )


class FakeGraph:
    """A graph that emits updates and can pause for HITL."""

    def __init__(
        self,
        *,
        pause: bool = False,
        fail: str | None = None,
    ) -> None:
        self.pause = pause
        self.fail = fail
        self.pending = pause
        self.hitl_decision: dict[str, Any] | None = None
        self.trace: list[TraceEvent] = []
        self.inputs: list[Any] = []

    def _add(self, node: str, event: str, **data: Any) -> TraceEvent:
        item = TraceEvent(node=node, event=event, data=data)
        self.trace.append(item)
        return item

    async def astream(
        self,
        payload: Any,
        *,
        config: dict[str, Any] | None = None,
        stream_mode: Any = None,
    ) -> AsyncIterator[dict[str, Any]]:
        del config, stream_mode
        self.inputs.append(payload)
        if self.fail:
            raise RuntimeError(self.fail)
        if isinstance(payload, Command):
            resume = getattr(payload, "resume", None)
            if isinstance(resume, dict):
                self.hitl_decision = resume
            self.pending = False
            yield {
                "writer": {
                    "status": "writing",
                    "trace": [self._add("writer", "report_created", claims=1)],
                }
            }
            return
        yield {
            "supervisor": {
                "status": "researching",
                "trace": [self._add("supervisor", "route_selected", next="planner")],
            }
        }
        if self.pending:
            yield {
                "approval": {
                    "status": "awaiting_approval",
                    "trace": [self._add("approval", "interrupt", notes=1)],
                }
            }
            return
        yield {
            "writer": {
                "status": "done",
                "trace": [self._add("writer", "report_created", claims=1)],
            }
        }

    async def aget_state(self, config: dict[str, Any] | None = None) -> Any:
        del config
        values: dict[str, Any] = {
            "status": "awaiting_approval" if self.pending else "done",
            "trace": list(self.trace),
            "usage": Usage(llm_calls=2, total_tokens=100, search_calls=1),
            "errors": [],
            "report": None,
            "hitl": self.hitl_decision,
        }
        if self.pending:
            return SimpleNamespace(
                values=values,
                interrupts=(
                    SimpleNamespace(
                        value={
                            "question": "What is a transformer?",
                            "analysis_summary": "One supported note.",
                            "notes": [{"subquestion": "What is a transformer?"}],
                            "sources": [],
                        }
                    ),
                ),
            )
        if self.hitl_decision and not self.hitl_decision.get("approved"):
            values["status"] = "failed"
            values["errors"] = ["Human reviewer rejected the draft before writing."]
            return SimpleNamespace(values=values, interrupts=())
        values["report"] = make_report()
        return SimpleNamespace(values=values, interrupts=())


async def wait_for(client: AsyncClient, run_id: str, status: str) -> dict[str, Any]:
    for _ in range(200):
        response = await client.get(f"/v1/research/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] == status:
            return payload
        await asyncio.sleep(0.01)
    raise AssertionError(f"Run {run_id} did not reach {status}: {payload}")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="groq",
        llm_model="test-main-model",
        llm_fast_model="test-fast-model",
        llm_fallback_provider=None,
        groq_api_key="gsk-test-secret",
        max_llm_calls=20,
        max_tokens=100_000,
        max_rounds=2,
    )


async def test_run_completes_and_exposes_report(settings: Settings) -> None:
    graph = FakeGraph()
    app = create_app(settings=settings, graph=graph, api_rate_limit_per_minute=1_000)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/v1/research",
                json={"question": "What is a transformer?", "run_id": "api-ok"},
            )
            assert created.status_code == 202
            assert created.json()["run_id"] == "api-ok"

            view = await wait_for(client, "api-ok", "completed")
            assert view["report"]["title"] == "Test report"
            assert view["report"]["sources"][0]["source_id"] == "src_1"
            assert view["usage"]["llm_calls"] == 2
            assert view["errors"] == []
            assert view["status_url"] == "/v1/research/api-ok"

            events = await client.get("/v1/research/api-ok/events")
            assert events.status_code == 200
            assert "report_created" in events.text
            assert '"type": "end"' in events.text


async def test_sse_replays_and_ends(settings: Settings) -> None:
    app = create_app(settings=settings, graph=FakeGraph())
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/v1/research",
                json={"question": "What is a transformer?", "run_id": "api-sse"},
            )
            await wait_for(client, "api-sse", "completed")
            async with client.stream(
                "GET",
                "/v1/research/api-sse/events",
            ) as response:
                body = ""
                async for chunk in response.aiter_text():
                    body += chunk
                    if '"type": "end"' in body:
                        break
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            assert "route_selected" in body
            assert '"type": "end"' in body


async def test_hitl_approval_resumes(settings: Settings) -> None:
    app = create_app(settings=settings, graph=FakeGraph(pause=True))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/v1/research",
                json={"question": "What is a transformer?", "hitl": True, "run_id": "api-hitl"},
            )
            paused = await wait_for(client, "api-hitl", "awaiting_approval")
            assert paused["interrupt"]["analysis_summary"] == "One supported note."

            decision = await client.post(
                "/v1/research/api-hitl/approve",
                json={"approved": True, "feedback": "Looks good."},
            )
            assert decision.status_code == 202

            completed = await wait_for(client, "api-hitl", "completed")
            assert completed["report"] is not None
            assert not completed["interrupt"]


async def test_hitl_rejection_is_visible(settings: Settings) -> None:
    app = create_app(settings=settings, graph=FakeGraph(pause=True))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/v1/research",
                json={"question": "What is a transformer?", "hitl": True, "run_id": "api-reject"},
            )
            await wait_for(client, "api-reject", "awaiting_approval")
            rejected = await client.post(
                "/v1/research/api-reject/approve",
                json={"approved": False, "feedback": "Missing sources."},
            )
            assert rejected.status_code == 202

            final = await wait_for(client, "api-reject", "rejected")
            assert final["report"] is None
            assert "rejected" in " ".join(final["errors"]).lower()


async def test_errors_are_redacted(settings: Settings) -> None:
    graph = FakeGraph(fail="provider failed with gsk-test-secret and gsk-other-secret")
    app = create_app(settings=settings, graph=graph)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/v1/research",
                json={"question": "What is a transformer?", "run_id": "api-error"},
            )
            view = await wait_for(client, "api-error", "failed")
            text = str(view)
            assert "gsk-test-secret" not in text
            assert "gsk-other-secret" not in text
            assert "[redacted]" in text


async def test_health_does_not_expose_secrets(settings: Settings) -> None:
    app = create_app(settings=settings, graph=FakeGraph())
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "ok"
            assert payload["provider"]["api_key_configured"] is True
            assert payload["checkpointer"]["backend"] == "injected"
            assert "gsk-test-secret" not in response.text


async def test_duplicate_and_invalid_run_ids(settings: Settings) -> None:
    app = create_app(settings=settings, graph=FakeGraph())
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/v1/research",
                json={"question": "What is a transformer?", "run_id": "same-id"},
            )
            assert first.status_code == 202
            duplicate = await client.post(
                "/v1/research",
                json={"question": "Another question?", "run_id": "same-id"},
            )
            assert duplicate.status_code == 409
            invalid = await client.post(
                "/v1/research",
                json={"question": "Another question?", "run_id": "bad id!"},
            )
            assert invalid.status_code == 422


async def test_rate_limit(settings: Settings) -> None:
    app = create_app(settings=settings, graph=FakeGraph())
    app.state.rate_limiter = RateLimiter(max_requests=1, window_s=60)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/v1/research",
                json={"question": "First question?", "run_id": "rate-1"},
            )
            assert first.status_code == 202
            second = await client.post(
                "/v1/research",
                json={"question": "Second question?", "run_id": "rate-2"},
            )
            assert second.status_code == 429
            assert "Retry-After" in second.headers


async def test_ui_files_are_served(settings: Settings) -> None:
    app = create_app(settings=settings, graph=FakeGraph())
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            page = await client.get("/")
            assert page.status_code == 200
            assert "Research Agents" in page.text
            script = await client.get("/static/app.js")
            assert script.status_code == 200
            assert "EventSource" in script.text


async def test_real_graph_pauses_and_resumes_through_api(settings: Settings) -> None:
    responses = {
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
    hitl_settings = settings.model_copy(update={"hitl": True})
    services = AgentServices(
        llm=FakeLLM(responses),
        researcher=StubResearcher(),
        settings=hitl_settings,
        budget=BudgetGuard(hitl_settings),
    )
    graph = build_graph(services, checkpointer=MemorySaver())
    app = create_app(settings=hitl_settings, graph=graph)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/v1/research",
                json={
                    "question": "What is the evidence?",
                    "hitl": True,
                    "run_id": "real-graph",
                },
            )
            paused = await wait_for(client, "real-graph", "awaiting_approval")
            assert paused["interrupt"] is not None
            assert paused["trace"]

            await client.post(
                "/v1/research/real-graph/approve",
                json={"approved": True, "feedback": "Looks good."},
            )
            completed = await wait_for(client, "real-graph", "completed")
            assert completed["report"]["answer_markdown"] == "A supported claim. [src_1]"
            assert any(item["event"] == "hitl_decision" for item in completed["trace"])
