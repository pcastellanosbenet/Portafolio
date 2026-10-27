"""Tests for execution, validation, retries, limits and policy."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.config import Settings
from src.gateway.audit import AuditLog
from src.gateway.catalog import Catalog
from src.gateway.executor import ToolExecutor
from src.gateway.policy import PolicyEngine
from tests.fakes import FakeUpstream


def build(settings: Settings, upstream: FakeUpstream, policy: PolicyEngine | None = None):
    catalog = Catalog()
    catalog.register(upstream.name, upstream.tools)
    audit = AuditLog(":memory:")
    executor = ToolExecutor(
        {upstream.name: upstream},
        settings,
        audit,
        policy or PolicyEngine("auto"),
    )
    return catalog, executor, audit


async def execute(executor: ToolExecutor, descriptor, arguments: dict[str, Any]):
    return await executor.execute(
        descriptor,
        arguments,
        trace_id="trace-test",
        protocol_version="2026-07-28",
        client_name="pytest",
    )


async def test_successful_call_is_audited(settings: Settings) -> None:
    upstream = FakeUpstream("docs", output_size=5)
    catalog, executor, audit = build(settings, upstream)
    descriptor = catalog.get("docs__search_docs")
    assert descriptor is not None

    result = await execute(executor, descriptor, {"query": "mcp"})
    assert not result.result.is_error
    assert result.result.structured_content == {"result": "xxxxx"}
    assert upstream.calls == [("search_docs", {"query": "mcp"})]
    assert audit.recent(1)[0]["status"] == "ok"


async def test_invalid_arguments_are_reported_to_the_model(settings: Settings) -> None:
    upstream = FakeUpstream("docs")
    catalog, executor, audit = build(settings, upstream)
    descriptor = catalog.get("docs__search_docs")
    assert descriptor is not None

    result = await execute(executor, descriptor, {})
    assert result.result.is_error
    assert "invalid arguments" in result.result.content[0].text
    assert upstream.calls == []
    assert audit.recent(1)[0]["status"] == "invalid_arguments"


async def test_transient_failure_is_retried(settings: Settings) -> None:
    upstream = FakeUpstream("docs", fail_times=1, output_size=3)
    catalog, executor, _ = build(settings, upstream)
    descriptor = catalog.get("docs__search_docs")
    assert descriptor is not None

    result = await execute(executor, descriptor, {"query": "mcp"})
    assert not result.result.is_error
    assert result.attempts == 2


async def test_timeout_is_retried_and_reported(settings: Settings) -> None:
    settings = settings.model_copy(
        update={"gateway_upstream_timeout_s": 0.05, "gateway_max_retries": 1}
    )
    upstream = FakeUpstream("docs", delay_s=0.2)
    catalog, executor, audit = build(settings, upstream)
    descriptor = catalog.get("docs__search_docs")
    assert descriptor is not None

    result = await execute(executor, descriptor, {"query": "mcp"})
    assert result.result.is_error
    assert result.attempts == 2
    assert audit.recent(1)[0]["status"] == "error"


async def test_oversized_output_is_truncated(settings: Settings) -> None:
    settings = settings.model_copy(update={"gateway_max_output_bytes": 512})
    upstream = FakeUpstream("docs", output_size=5000)
    catalog, executor, _ = build(settings, upstream)
    descriptor = catalog.get("docs__search_docs")
    assert descriptor is not None

    result = await execute(executor, descriptor, {"query": "mcp"})
    assert result.truncated
    assert result.result.meta == {"truncated": True}
    assert len(result.result.model_dump_json()) < 1024
    assert "truncated by gateway" in result.result.content[-1].text


async def test_allowlist_denies_unknown_tools(settings: Settings) -> None:
    upstream = FakeUpstream("docs")
    catalog, executor, audit = build(
        settings, upstream, PolicyEngine("auto", allowlist={"docs__other"})
    )
    descriptor = catalog.get("docs__search_docs")
    assert descriptor is not None

    result = await execute(executor, descriptor, {"query": "mcp"})
    assert result.result.is_error
    assert "policy denied" in result.result.content[0].text
    assert upstream.calls == []
    assert audit.recent(1)[0]["status"] == "policy_denied"


async def test_destructive_tool_requires_approval(settings: Settings) -> None:
    upstream = FakeUpstream("docs")
    catalog, executor, audit = build(settings, upstream, PolicyEngine("risk"))
    descriptor = catalog.get("docs__delete_namespace")
    assert descriptor is not None

    result = await execute(executor, descriptor, {"namespace": "staging"})
    assert result.result.is_error
    assert "approval required" in result.result.content[0].text
    assert audit.recent(1)[0]["status"] == "approval_required"


async def test_progress_callback_is_forwarded(settings: Settings) -> None:
    upstream = FakeUpstream("docs", output_size=3)
    catalog, executor, _ = build(settings, upstream)
    descriptor = catalog.get("docs__search_docs")
    assert descriptor is not None
    events: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        events.append((progress, total, message))

    await executor.execute(
        descriptor,
        {"query": "mcp"},
        trace_id="trace-progress",
        progress_callback=on_progress,
    )
    assert events == [(1, 1, "done")]


async def test_cancellation_propagates_to_the_upstream(settings: Settings) -> None:
    upstream = FakeUpstream("docs", delay_s=5)
    catalog, executor, _ = build(settings, upstream)
    descriptor = catalog.get("docs__search_docs")
    assert descriptor is not None

    task = asyncio.create_task(execute(executor, descriptor, {"query": "mcp"}))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert upstream.cancelled


@pytest.mark.parametrize("name", ["docs__search_docs", "docs__delete_namespace"])
async def test_descriptors_exist_for_reference_tools(settings: Settings, name: str) -> None:
    catalog, _, _ = build(settings, FakeUpstream("docs"))
    assert catalog.get(name) is not None
