"""End-to-end tests against the gateway's low-level MCP server."""

from __future__ import annotations

import pytest
from mcp import Client, MCPError
from mcp.types import CallToolResult, ElicitRequestParams, ElicitResult

from src.config import Settings
from src.gateway.audit import AuditLog
from src.gateway.policy import PolicyEngine
from src.gateway.server import Gateway
from tests.fakes import FakeUpstream, make_tool


async def test_client_lists_and_calls_aggregated_tools(gateway) -> None:
    instance, upstream = gateway
    async with Client(instance.build_server()) as client:
        assert client.protocol_version == "2026-07-28"
        tools = await client.list_tools()
        assert len(tools.tools) == 25
        assert tools.tools[0].name.startswith("docs__")

        result = await client.call_tool("docs__search_docs", {"query": "mcp"})
        assert isinstance(result, CallToolResult)
        assert not result.is_error
        assert upstream.calls == [("search_docs", {"query": "mcp"})]


async def test_unknown_tool_is_a_protocol_error(gateway) -> None:
    instance, _ = gateway
    async with Client(instance.build_server()) as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool("docs__missing", {})
        assert exc.value.code == -32602


async def test_health_reports_tool_counts(gateway) -> None:
    instance, _ = gateway
    health = instance.health()
    assert health["status"] == "ok"
    assert health["tools"] == 25
    assert health["upstreams"]["docs"] == {
        "connected": True,
        "tools": 25,
        "error": None,
    }


async def test_refresh_replaces_tools_atomically(gateway) -> None:
    instance, upstream = gateway
    upstream.tools = [make_tool("only_tool")]
    names = await instance.refresh("docs")
    assert names == ["docs__only_tool"]
    assert instance.health()["tools"] == 1


async def test_progress_events_reach_the_client(gateway) -> None:
    instance, _ = gateway
    events: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        events.append((progress, total, message))

    async with Client(instance.build_server()) as client:
        await client.call_tool(
            "docs__search_docs",
            {"query": "mcp"},
            progress_callback=on_progress,
        )
    assert events == [(1.0, 1.0, "done")]


async def test_upstreams_stop_in_reverse_order(settings: Settings) -> None:
    order: list[str] = []

    class OrderedUpstream(FakeUpstream):
        async def stop(self) -> None:
            order.append(self.name)
            await super().stop()

    instance = Gateway(
        settings,
        {"first": OrderedUpstream("first"), "second": OrderedUpstream("second")},
        audit=AuditLog(":memory:"),
        policy=PolicyEngine("auto"),
    )
    await instance.start()
    await instance.stop()
    assert order == ["second", "first"]


async def test_one_failed_upstream_does_not_break_the_gateway(settings: Settings) -> None:
    class BrokenUpstream(FakeUpstream):
        async def start(self) -> None:
            raise RuntimeError("boom")

    instance = Gateway(
        settings,
        {"broken": BrokenUpstream("broken", [make_tool("x")]), "docs": FakeUpstream("docs")},
        audit=AuditLog(":memory:"),
        policy=PolicyEngine("auto"),
    )
    await instance.start()
    try:
        assert instance.health()["status"] == "degraded"
        assert instance.health()["tools"] == 25
        assert "boom" in (instance.health()["upstreams"]["broken"]["error"] or "")
    finally:
        await instance.stop()


async def test_destructive_tool_runs_after_mrtr_approval() -> None:
    settings = Settings(
        gateway_db_path=":memory:",
        gateway_approval_mode="risk",
        gateway_max_retries=1,
        gateway_router_mode="static",
    )
    upstream = FakeUpstream("ops")
    instance = Gateway(
        settings,
        {"ops": upstream},
        audit=AuditLog(":memory:"),
        policy=PolicyEngine("risk"),
    )
    await instance.start()

    async def accept(
        _context: object, _params: ElicitRequestParams
    ) -> ElicitResult:
        return ElicitResult(action="accept", content={"approve": True})

    try:
        async with Client(
            instance.build_server(), elicitation_callback=accept
        ) as client:
            result = await client.call_tool("ops__restart_service", {"service": "api"})
        assert not result.is_error
        assert upstream.calls == [("restart_service", {"service": "api"})]
        assert result.meta is not None
        assert result.meta["trace_id"]
        assert [record["status"] for record in instance.audit.recent(2)] == [
            "ok",
            "approval_pending",
        ]
    finally:
        await instance.stop()


async def test_destructive_tool_is_denied_when_user_declines() -> None:
    settings = Settings(
        gateway_db_path=":memory:",
        gateway_approval_mode="risk",
        gateway_max_retries=1,
        gateway_router_mode="static",
    )
    upstream = FakeUpstream("ops")
    instance = Gateway(
        settings,
        {"ops": upstream},
        audit=AuditLog(":memory:"),
        policy=PolicyEngine("risk"),
    )
    await instance.start()

    async def decline(
        _context: object, _params: ElicitRequestParams
    ) -> ElicitResult:
        return ElicitResult(action="decline", content=None)

    try:
        async with Client(
            instance.build_server(), elicitation_callback=decline
        ) as client:
            result = await client.call_tool("ops__delete_namespace", {"namespace": "demo"})
        assert result.is_error
        assert "approval denied" in result.content[0].text
        assert result.meta is not None and result.meta["trace_id"]
        assert upstream.calls == []
        assert [record["status"] for record in instance.audit.recent(2)] == [
            "approval_denied",
            "approval_pending",
        ]
    finally:
        await instance.stop()


def test_approval_state_roundtrip_handles_binary_signatures() -> None:
    settings = Settings(gateway_db_path=":memory:")
    instance = Gateway(
        settings,
        {},
        audit=AuditLog(":memory:"),
        policy=PolicyEngine("risk"),
    )
    for index in range(200):
        payload = {
            "trace_id": f"trace-{index}",
            "tool": "ops__restart_service",
            "definition": "a" * 64,
            "args": "b" * 64,
            "exp": 2_000_000_000,
        }
        token = instance._seal_state(payload)
        assert instance._open_state(token) == payload
