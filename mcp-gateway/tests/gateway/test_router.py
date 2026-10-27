"""Tests for static, meta and hybrid tool disclosure."""

from __future__ import annotations

import pytest
from mcp import Client, MCPError

from src.config import Settings
from src.gateway.audit import AuditLog
from src.gateway.policy import PolicyEngine
from src.gateway.router import (
    FIND_TOOLS_NAME,
    INVOKE_TOOL_NAME,
    MODE_HYBRID,
    MODE_META,
    MODE_STATIC,
    QUERY_META_KEY,
    ToolRouter,
    count_tool_tokens,
)
from src.gateway.server import Gateway
from src.models import make_descriptor
from tests.fakes import FakeUpstream, demo_tools, make_tool


def descriptors():
    return [
        make_descriptor("docs", make_tool("list_docs", "List documents.")),
        make_descriptor("docs", make_tool("search_docs", "Search documentation.")),
        make_descriptor("ops", make_tool("list_services", "List services.")),
        make_descriptor(
            "ops",
            make_tool(
                "restart_service",
                "Restart a service.",
                {"type": "object", "properties": {"service": {"type": "string"}}},
            ),
        ),
        make_descriptor("research", make_tool("wikipedia_search", "Search Wikipedia.")),
        make_descriptor("research", make_tool("fetch_url", "Fetch an external URL.")),
    ]


def test_static_mode_exposes_every_descriptor() -> None:
    routed = ToolRouter(MODE_STATIC).route("anything", descriptors())
    assert [tool.name for tool in routed.tools] == [
        descriptor.name for descriptor in descriptors()
    ]
    assert not routed.fallback


def test_meta_mode_exposes_only_meta_tools() -> None:
    routed = ToolRouter(MODE_META).route("search docs", descriptors())
    assert [tool.name for tool in routed.tools] == [FIND_TOOLS_NAME, INVOKE_TOOL_NAME]
    assert routed.descriptors == []


def test_hybrid_mode_combines_fixed_ranked_and_meta_tools() -> None:
    routed = ToolRouter(MODE_HYBRID, top_k=2).route("restart service", descriptors())
    names = [tool.name for tool in routed.tools]
    assert "ops__list_services" in names
    assert "docs__list_docs" in names
    assert "research__wikipedia_search" in names
    assert "ops__restart_service" in names
    assert FIND_TOOLS_NAME in names and INVOKE_TOOL_NAME in names
    assert len(names) < len(descriptors()) + 2


def test_hybrid_falls_back_when_nothing_matches() -> None:
    routed = ToolRouter(MODE_HYBRID, top_k=2).route("zzzz", descriptors())
    assert routed.fallback
    assert [tool.name for tool in routed.tools][-2:] == [FIND_TOOLS_NAME, INVOKE_TOOL_NAME]


def test_tool_token_count_is_positive() -> None:
    routed = ToolRouter(MODE_STATIC).route("", descriptors())
    assert count_tool_tokens(routed.tools) > 0


async def test_meta_gateway_requires_find_and_invoke() -> None:
    settings = Settings(
        gateway_db_path=":memory:",
        gateway_router_mode=MODE_META,
        gateway_approval_mode="auto",
    )
    upstream = FakeUpstream("docs")
    instance = Gateway(
        settings,
        {"docs": upstream},
        audit=AuditLog(":memory:"),
        policy=PolicyEngine("auto"),
    )
    await instance.start()
    try:
        async with Client(instance.build_server()) as client:
            tools = await client.list_tools()
            assert [tool.name for tool in tools.tools] == [
                FIND_TOOLS_NAME,
                INVOKE_TOOL_NAME,
            ]
            found = await client.call_tool(FIND_TOOLS_NAME, {"query": "search docs"})
            assert found.structured_content["tools"][0]["name"] == "docs__search_docs"

            invoked = await client.call_tool(
                INVOKE_TOOL_NAME,
                {
                    "server": "docs",
                    "tool": "search_docs",
                    "arguments": {"query": "mcp"},
                },
            )
            assert not invoked.is_error
            assert upstream.calls == [("search_docs", {"query": "mcp"})]

            with pytest.raises(MCPError):
                await client.call_tool("docs__search_docs", {"query": "mcp"})
    finally:
        await instance.stop()


async def test_hybrid_listing_uses_query_meta() -> None:
    settings = Settings(
        gateway_db_path=":memory:",
        gateway_router_mode=MODE_HYBRID,
        gateway_top_k=3,
        gateway_approval_mode="auto",
    )
    upstream = FakeUpstream("docs", demo_tools())
    instance = Gateway(
        settings,
        {"docs": upstream},
        audit=AuditLog(":memory:"),
        policy=PolicyEngine("auto"),
    )
    await instance.start()
    try:
        async with Client(instance.build_server()) as client:
            default = await client.list_tools()
            assert len(default.tools) == 3
            assert default.ttl_ms == 60_000
            assert default.cache_scope == "public"

            scoped = await client.list_tools(
                meta={QUERY_META_KEY: "restart service docs"}
            )
            names = [tool.name for tool in scoped.tools]
            assert "docs__restart_service" in names
            assert FIND_TOOLS_NAME in names and INVOKE_TOOL_NAME in names
            assert scoped.ttl_ms == 0
            assert scoped.cache_scope == "private"
    finally:
        await instance.stop()
