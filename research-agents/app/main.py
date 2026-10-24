"""FastAPI application, lifecycle and HTTP/SSE routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.manager import (
    RunConflictError,
    RunManager,
    RunNotFoundError,
    RunRecord,
)
from app.rate_limit import RateLimiter
from app.schemas import (
    ApprovalAccepted,
    ApprovalRequest,
    CheckpointerHealth,
    HealthResponse,
    ProviderHealth,
    ResearchAccepted,
    ResearchRequest,
    RunView,
)
from src.checkpoint import open_async_checkpointer
from src.config import Settings
from src.graph import build_graph
from src.services import build_services

APP_VERSION = "0.1.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
_SSE_HEARTBEAT_S = 15.0


def _urls(run_id: str) -> tuple[str, str]:
    return f"/v1/research/{run_id}", f"/v1/research/{run_id}/events"


def _view(record: RunRecord) -> RunView:
    status_url, events_url = _urls(record.run_id)
    return RunView(
        run_id=record.run_id,
        thread_id=record.thread_id,
        question=record.question,
        language=record.language,
        hitl=record.hitl,
        status=record.status,
        graph_status=record.graph_status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        interrupt=record.interrupt,
        report=record.report,
        usage=record.usage,
        errors=record.errors,
        trace=record.trace,
        status_url=status_url,
        events_url=events_url,
    )


def _manager(request: Request) -> RunManager:
    return request.app.state.manager


def _enforce_rate_limit(request: Request) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    key = request.client.host if request.client else "anonymous"
    if not limiter.allow(key):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Retry later.",
            headers={"Retry-After": str(limiter.retry_after(key))},
        )


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _event_stream(
    request: Request,
    record: RunRecord,
) -> AsyncIterator[str]:
    queue, replay = record.subscribe()
    try:
        for event in replay:
            yield _sse(event)
        if record.terminal:
            return
        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(),
                    timeout=_SSE_HEARTBEAT_S,
                )
            except TimeoutError:
                if await request.is_disconnected():
                    break
                yield ": keep-alive\n\n"
                continue
            yield _sse(event)
            if event.get("type") == "end" and event.get("status") != "awaiting_approval":
                break
            if await request.is_disconnected():
                break
    finally:
        record.unsubscribe(queue)


def create_app(
    *,
    settings: Settings | None = None,
    graph: Any | None = None,
    graph_hitl: Any | None = None,
    manager: RunManager | None = None,
    api_rate_limit_per_minute: int = 30,
) -> FastAPI:
    """Create the FastAPI application.

    ``graph`` and ``manager`` are injection points for tests. With neither
    supplied, the lifespan opens the SQLite checkpointer and builds the real
    graph from the environment.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved = settings or Settings(_env_file=PROJECT_ROOT / ".env")
        resolved.ensure_runtime_dirs()
        app.state.settings = resolved
        app.state.started_at = datetime.now(UTC)
        app.state.checkpointer_backend = "injected"
        app.state.checkpointer_status = "ok"
        app.state.services = None

        if manager is not None:
            app.state.manager = manager
            try:
                yield
            finally:
                await manager.close()
            return

        if graph is not None:
            active = RunManager(
                graph=graph,
                graph_hitl=graph_hitl or graph,
                settings=resolved,
            )
            app.state.manager = active
            try:
                yield
            finally:
                await active.close()
            return

        async with AsyncExitStack() as stack:
            saver = await stack.enter_async_context(
                open_async_checkpointer(resolved.checkpoint_path)
            )
            services = build_services(resolved)
            real_graph = build_graph(services, checkpointer=saver)
            if resolved.hitl:
                hitl_graph = real_graph
            else:
                hitl_services = replace(
                    services,
                    settings=resolved.model_copy(update={"hitl": True}),
                )
                hitl_graph = build_graph(hitl_services, checkpointer=saver)
            active = RunManager(
                graph=real_graph,
                graph_hitl=hitl_graph,
                settings=resolved,
            )
            app.state.manager = active
            app.state.services = services
            app.state.checkpointer_backend = "sqlite"
            app.state.checkpointer_status = "ok"
            try:
                yield
            finally:
                await active.close()

    app = FastAPI(
        title="Research Agents API",
        description="Multi-agent research demo with SSE trace and human approval.",
        version=APP_VERSION,
        lifespan=lifespan,
    )
    app.state.rate_limiter = RateLimiter(
        max_requests=api_rate_limit_per_minute,
        window_s=60.0,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health(request: Request) -> HealthResponse:
        active: RunManager = request.app.state.manager
        effective: Settings = request.app.state.settings
        key_ok = effective.has_api_key_for(effective.llm_provider)
        fallback_ok = bool(
            effective.llm_fallback_provider
            and effective.has_api_key_for(effective.llm_fallback_provider)
        )
        checkpointer_status = getattr(
            request.app.state,
            "checkpointer_status",
            "unavailable",
        )
        healthy = key_ok and checkpointer_status == "ok"
        return HealthResponse(
            status="ok" if healthy else "degraded",
            version=APP_VERSION,
            checkpointer=CheckpointerHealth(
                backend=request.app.state.checkpointer_backend,
                status=checkpointer_status,
            ),
            provider=ProviderHealth(
                name=effective.llm_provider,
                model=effective.llm_model,
                fast_model=effective.fast_model,
                api_key_configured=key_ok,
                fallback_provider=effective.llm_fallback_provider,
                fallback_api_key_configured=fallback_ok,
            ),
            search_backend=effective.search_backend,
            active_runs=active.active_count,
        )

    @app.post(
        "/v1/research",
        response_model=ResearchAccepted,
        status_code=202,
        tags=["research"],
        dependencies=[Depends(_enforce_rate_limit)],
    )
    async def start_research(
        body: ResearchRequest,
        request: Request,
    ) -> ResearchAccepted:
        active: RunManager = request.app.state.manager
        try:
            record = await active.start(body)
        except RunConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        status_url, events_url = _urls(record.run_id)
        return ResearchAccepted(
            run_id=record.run_id,
            thread_id=record.thread_id,
            status=record.status,
            status_url=status_url,
            events_url=events_url,
        )

    @app.get(
        "/v1/research/{run_id}",
        response_model=RunView,
        tags=["research"],
    )
    async def get_research(run_id: str, request: Request) -> RunView:
        active: RunManager = request.app.state.manager
        try:
            return _view(active.get(run_id))
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found.") from exc

    @app.post(
        "/v1/research/{run_id}/approve",
        response_model=ApprovalAccepted,
        status_code=202,
        tags=["research"],
        dependencies=[Depends(_enforce_rate_limit)],
    )
    async def approve_research(
        run_id: str,
        body: ApprovalRequest,
        request: Request,
    ) -> ApprovalAccepted:
        active: RunManager = request.app.state.manager
        try:
            record = await active.approve(
                run_id,
                approved=body.approved,
                feedback=body.feedback,
            )
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found.") from exc
        except RunConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        status_url, _ = _urls(record.run_id)
        return ApprovalAccepted(
            run_id=record.run_id,
            status=record.status,
            status_url=status_url,
        )

    @app.get(
        "/v1/research/{run_id}/events",
        response_class=StreamingResponse,
        tags=["research"],
    )
    async def research_events(run_id: str, request: Request) -> StreamingResponse:
        active: RunManager = request.app.state.manager
        try:
            record = active.get(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found.") from exc
        return StreamingResponse(
            _event_stream(request, record),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
