"""Checkpointing and resume helpers for durable research runs."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from src.models import (
    Analysis,
    Claim,
    Critique,
    EvidenceItem,
    FinalReport,
    Note,
    ReportDraft,
    ResearchAnswer,
    ResearchBrief,
    ResearchOutput,
    ResearchPlan,
    ResearchTask,
    Route,
    Source,
    SubQuestion,
    Usage,
)
from src.state import ResearchState
from src.trace import TraceEvent

# Only these application types may be reconstructed from a checkpoint. The
# default LangGraph serializer is permissive; an explicit allowlist keeps a
# compromised SQLite file from becoming an arbitrary-code-execution vector.
CHECKPOINT_TYPES = (
    Analysis,
    Claim,
    Critique,
    EvidenceItem,
    FinalReport,
    Note,
    ReportDraft,
    ResearchAnswer,
    ResearchBrief,
    ResearchOutput,
    ResearchPlan,
    ResearchTask,
    Route,
    Source,
    SubQuestion,
    TraceEvent,
    Usage,
)


@asynccontextmanager
async def open_async_checkpointer(path: Path) -> AsyncIterator[AsyncSqliteSaver]:
    """Open the async SQLite checkpointer used by the CLI and future API."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serde = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)
    async with aiosqlite.connect(str(path)) as connection:
        yield AsyncSqliteSaver(connection, serde=serde)


def _config(
    thread_id: str,
    *,
    recursion_limit: int,
    max_concurrency: int | None,
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    run_config: dict[str, Any] = {
        "recursion_limit": recursion_limit,
        "configurable": {"thread_id": thread_id},
    }
    if max_concurrency is not None:
        run_config["max_concurrency"] = max_concurrency
    if config:
        configured = dict(run_config.get("configurable", {}))
        configured.update(config.get("configurable", {}))
        run_config.update(config)
        run_config["configurable"] = configured
    return run_config


def resume_research(
    graph: Any,
    *,
    thread_id: str,
    decision: dict[str, object] | bool | str | None = None,
    recursion_limit: int = 50,
    max_concurrency: int | None = None,
    config: dict[str, Any] | None = None,
) -> ResearchState:
    """Resume an interrupted or failed run on the same thread.

    ``decision=None`` retries the checkpoint without an ``interrupt`` resume
    value. This is the path used after a simulated process crash.
    """
    run_config = _config(
        thread_id,
        recursion_limit=recursion_limit,
        max_concurrency=max_concurrency,
        config=config,
    )
    payload: Any = None if decision is None else Command(resume=decision)
    return graph.invoke(payload, config=run_config)


async def run_research_async(
    graph: Any,
    brief: ResearchBrief,
    *,
    run_id: str | None = None,
    thread_id: str | None = None,
    recursion_limit: int = 50,
    max_concurrency: int | None = None,
    config: dict[str, Any] | None = None,
) -> ResearchState:
    """Async fresh run bound to a checkpoint thread."""
    from src.state import initial_state

    state = initial_state(brief, run_id=run_id)
    thread = thread_id or state["run_id"]
    run_config = _config(
        thread,
        recursion_limit=recursion_limit,
        max_concurrency=max_concurrency,
        config=config,
    )
    return await graph.ainvoke(state, config=run_config)


async def resume_research_async(
    graph: Any,
    *,
    thread_id: str,
    decision: dict[str, object] | bool | str | None = None,
    recursion_limit: int = 50,
    max_concurrency: int | None = None,
    config: dict[str, Any] | None = None,
) -> ResearchState:
    """Async resume after HITL or a process-level failure."""
    run_config = _config(
        thread_id,
        recursion_limit=recursion_limit,
        max_concurrency=max_concurrency,
        config=config,
    )
    payload: Any = None if decision is None else Command(resume=decision)
    return await graph.ainvoke(payload, config=run_config)
