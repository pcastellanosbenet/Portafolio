"""In-process run registry and SSE event fan-out for the API."""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command
from pydantic import BaseModel

from app.schemas import ResearchRequest
from src.config import Settings
from src.models import FinalReport, ResearchBrief, Usage
from src.state import initial_state
from src.trace import TraceEvent

TERMINAL_STATUSES = {"completed", "failed", "rejected"}
_SECRET_PATTERN = re.compile(r"(?:gsk_|sk-|AIza)[A-Za-z0-9_\-]{8,}")


class RunConflictError(Exception):
    """The requested operation conflicts with the current run state."""


class RunNotFoundError(Exception):
    """The requested run does not exist."""


def _jsonable(value: Any) -> Any:
    """Convert application models and datetimes into JSON-safe values."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _redact(message: str, settings: Settings) -> str:
    """Remove configured secrets and common key shapes from public errors."""
    for secret in (
        settings.groq_api_key,
        settings.gemini_api_key,
        settings.tavily_api_key,
    ):
        if secret is None:
            continue
        value = secret.get_secret_value()
        if value:
            message = message.replace(value, "[redacted]")
    message = _SECRET_PATTERN.sub("[redacted]", message)
    return message[:800]


def _redact_value(value: Any, settings: Settings) -> Any:
    """Recursively redact strings in trace payloads."""
    if isinstance(value, str):
        return _redact(value, settings)
    if isinstance(value, dict):
        return {str(key): _redact_value(item, settings) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(item, settings) for item in value]
    return value


def _interrupt_from_snapshot(
    values: dict[str, Any],
    interrupts: Any,
) -> dict[str, Any] | None:
    if interrupts:
        first = interrupts[0]
        value = getattr(first, "value", first)
        return value if isinstance(value, dict) else {"value": _jsonable(value)}
    raw = values.get("__interrupt__")
    if not raw:
        return None
    first = raw[0] if isinstance(raw, (list, tuple)) else raw
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else {"value": _jsonable(value)}


def _trace_events(values: list[Any] | None) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    for item in values or []:
        if isinstance(item, TraceEvent):
            events.append(item)
        elif isinstance(item, dict):
            events.append(TraceEvent.model_validate(item))
    return events


@dataclass
class RunRecord:
    """Mutable state for one API run."""

    run_id: str
    thread_id: str
    question: str
    language: str
    hitl: bool
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: str = "queued"
    graph_status: str = "planning"
    interrupt: dict[str, Any] | None = None
    report: FinalReport | None = None
    usage: Usage = field(default_factory=Usage)
    errors: list[str] = field(default_factory=list)
    trace: list[TraceEvent] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    seen_trace: set[tuple[str, str, str, str]] = field(default_factory=set)
    task: asyncio.Task[None] | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)

    def publish(self, event: dict[str, Any]) -> None:
        payload = _jsonable(event)
        self.events.append(payload)
        self.touch()
        for queue in tuple(self.subscribers):
            queue.put_nowait(payload)

    def subscribe(self) -> tuple[asyncio.Queue[dict[str, Any]], list[dict[str, Any]]]:
        """Register a listener and return the already published events.

        Subscription and snapshot happen without an ``await`` so no event can
        be published between the two operations in the event loop.
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.subscribers.add(queue)
        return queue, list(self.events)

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(queue)


class RunManager:
    """Schedule research graphs and expose their state as event streams."""

    def __init__(
        self,
        *,
        graph: Any,
        settings: Settings,
        graph_hitl: Any | None = None,
        recursion_limit: int = 50,
        max_runs: int = 200,
    ) -> None:
        self.graph = graph
        self.graph_hitl = graph_hitl or graph
        self.settings = settings
        self.recursion_limit = recursion_limit
        self.max_runs = max_runs
        self.runs: dict[str, RunRecord] = {}

    def _graph_for(self, hitl: bool) -> Any:
        return self.graph_hitl if hitl else self.graph

    def get(self, run_id: str) -> RunRecord:
        record = self.runs.get(run_id)
        if record is None:
            raise RunNotFoundError(run_id)
        return record

    @property
    def active_count(self) -> int:
        return sum(not record.terminal for record in self.runs.values())

    def _remember(self, record: RunRecord) -> None:
        self.runs[record.run_id] = record
        if len(self.runs) > self.max_runs:
            terminal = [
                item
                for item in self.runs.values()
                if item.terminal and item.subscribers == set()
            ]
            terminal.sort(key=lambda item: item.updated_at)
            for item in terminal[: max(0, len(self.runs) - self.max_runs)]:
                self.runs.pop(item.run_id, None)

    async def start(self, request: ResearchRequest) -> RunRecord:
        run_id = request.run_id or uuid.uuid4().hex
        if run_id in self.runs:
            raise RunConflictError(f"Run {run_id!r} already exists.")
        hitl = self.settings.hitl if request.hitl is None else request.hitl
        brief = ResearchBrief(question=request.question, language=request.language)
        state = initial_state(brief, run_id=run_id)
        record = RunRecord(
            run_id=run_id,
            thread_id=run_id,
            question=request.question,
            language=request.language,
            hitl=hitl,
        )
        self._remember(record)
        record.publish(
            {
                "type": "status",
                "run_id": run_id,
                "status": record.status,
                "graph_status": record.graph_status,
            }
        )
        record.task = asyncio.create_task(
            self._drive(record, payload=state),
            name=f"research-{run_id}",
        )
        return record

    async def approve(
        self,
        run_id: str,
        *,
        approved: bool,
        feedback: str = "",
    ) -> RunRecord:
        record = self.get(run_id)
        async with record.lock:
            if record.status != "awaiting_approval":
                raise RunConflictError(
                    f"Run {run_id!r} is {record.status!r}, not awaiting approval."
                )
            record.status = "running"
            record.interrupt = None
            record.touch()
            record.publish(
                {
                    "type": "status",
                    "run_id": run_id,
                    "status": record.status,
                    "graph_status": record.graph_status,
                }
            )
            decision = {"approved": approved, "feedback": feedback}
            record.task = asyncio.create_task(
                self._drive(record, payload=Command(resume=decision)),
                name=f"research-resume-{run_id}",
            )
        return record

    async def close(self) -> None:
        tasks = [
            record.task
            for record in self.runs.values()
            if record.task is not None and not record.task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _publish_trace(self, record: RunRecord, event: TraceEvent) -> None:
        data = _redact_value(event.data, self.settings)
        key = (
            event.timestamp.isoformat(),
            event.node,
            event.event,
            str(sorted(data.items())),
        )
        if key in record.seen_trace:
            return
        record.seen_trace.add(key)
        payload = event.model_dump(mode="json")
        payload["data"] = data
        record.publish({"type": "trace", "run_id": record.run_id, **payload})

    def _consume_update(self, record: RunRecord, chunk: Any) -> None:
        if not isinstance(chunk, dict):
            return
        for node, update in chunk.items():
            if node == "__interrupt__" or not isinstance(update, dict):
                continue
            record.publish({"type": "node", "run_id": record.run_id, "node": node})
            graph_status = update.get("status")
            if isinstance(graph_status, str) and graph_status != record.graph_status:
                record.graph_status = graph_status
                record.publish(
                    {
                        "type": "status",
                        "run_id": record.run_id,
                        "status": record.status,
                        "graph_status": record.graph_status,
                    }
                )
            for event in _trace_events(update.get("trace")):
                self._publish_trace(record, event)

    def _finish(self, record: RunRecord, snapshot: Any) -> None:
        values = getattr(snapshot, "values", None) or {}
        interrupts = getattr(snapshot, "interrupts", ())
        record.trace = [
            event.model_copy(
                update={"data": _redact_value(event.data, self.settings)}
            )
            for event in _trace_events(values.get("trace"))
        ]
        for event in record.trace:
            self._publish_trace(record, event)

        usage = values.get("usage")
        if isinstance(usage, Usage):
            record.usage = usage
        elif isinstance(usage, dict):
            record.usage = Usage.model_validate(usage)

        record.errors = [
            _redact(str(item), self.settings) for item in values.get("errors", [])
        ]
        report = values.get("report")
        if isinstance(report, FinalReport):
            record.report = report
        elif isinstance(report, dict):
            record.report = FinalReport.model_validate(report)

        graph_status = values.get("status")
        if isinstance(graph_status, str):
            record.graph_status = graph_status
        record.interrupt = _interrupt_from_snapshot(values, interrupts)

        if record.interrupt:
            record.status = "awaiting_approval"
            record.graph_status = "awaiting_approval"
        elif record.report is not None:
            record.status = "completed"
        elif values.get("hitl") and values["hitl"].get("approved") is False:
            record.status = "rejected"
        else:
            record.status = "failed"

        record.touch()
        record.publish(
            {
                "type": "status",
                "run_id": record.run_id,
                "status": record.status,
                "graph_status": record.graph_status,
            }
        )
        record.publish(
            {
                "type": "end",
                "run_id": record.run_id,
                "status": record.status,
                "graph_status": record.graph_status,
            }
        )

    async def _drive(self, record: RunRecord, *, payload: Any) -> None:
        graph = self._graph_for(record.hitl)
        if record.status == "queued":
            record.status = "running"
            record.touch()
        config: dict[str, Any] = {
            "recursion_limit": self.recursion_limit,
            "configurable": {"thread_id": record.thread_id},
        }
        if self.settings.max_workers:
            config["max_concurrency"] = self.settings.max_workers
        try:
            record.publish(
                {
                    "type": "status",
                    "run_id": record.run_id,
                    "status": record.status,
                    "graph_status": record.graph_status,
                }
            )
            async for chunk in graph.astream(
                payload,
                config=config,
                stream_mode="updates",
            ):
                self._consume_update(record, chunk)
            snapshot = await graph.aget_state(config)
            self._finish(record, snapshot)
        except asyncio.CancelledError:
            record.status = "failed"
            record.errors = ["Run cancelled during application shutdown."]
            record.touch()
            record.publish(
                {
                    "type": "end",
                    "run_id": record.run_id,
                    "status": record.status,
                    "graph_status": record.graph_status,
                }
            )
            raise
        except Exception as exc:  # noqa: BLE001 - expose a safe error to the client
            record.status = "failed"
            record.errors = [_redact(f"{type(exc).__name__}: {exc}", self.settings)]
            record.touch()
            record.publish(
                {
                    "type": "run_error",
                    "run_id": record.run_id,
                    "message": record.errors[0],
                }
            )
            record.publish(
                {
                    "type": "end",
                    "run_id": record.run_id,
                    "status": record.status,
                    "graph_status": record.graph_status,
                }
            )
