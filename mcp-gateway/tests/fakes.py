"""Deterministic upstream doubles used by the test suite."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

ProgressCallback = Callable[[float, float | None, str | None], Awaitable[None]]


def make_tool(
    name: str,
    description: str = "A test tool.",
    schema: dict[str, Any] | None = None,
    *,
    read_only: bool = True,
    destructive: bool = False,
) -> Tool:
    """Build a tool definition with optional risk annotations."""
    return Tool(
        name=name,
        description=description,
        inputSchema=schema or {"type": "object", "properties": {}},
        annotations=ToolAnnotations(
            readOnlyHint=read_only,
            destructiveHint=destructive,
        ),
    )


def demo_tools(count: int = 25) -> list[Tool]:
    """Return a realistic mix of read, write and destructive tools."""
    tools = [
        make_tool(
            "search_docs",
            "Search the documentation corpus.",
            {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        make_tool("read_doc", "Read one document.", {"type": "object"}),
        make_tool("list_docs", "List available documents."),
        make_tool("outline_doc", "Return the outline of a document."),
        make_tool("cite_doc", "Return a citation for a document."),
        make_tool("wikipedia_search", "Search Wikipedia."),
        make_tool("wikipedia_get", "Read a Wikipedia page."),
        make_tool("arxiv_search", "Search arXiv."),
        make_tool("arxiv_get", "Read an arXiv paper."),
        make_tool("fetch_url", "Fetch a URL.", read_only=True),
        make_tool("get_service_status", "Return service status."),
        make_tool("query_metrics", "Query service metrics."),
        make_tool("list_tickets", "List incidents."),
        make_tool("get_ticket", "Read one incident."),
        make_tool("search_logs", "Search recent logs."),
        make_tool("deploy_history", "Return recent deploys."),
        make_tool(
            "create_ticket",
            "Create an incident ticket.",
            {"type": "object", "properties": {"title": {"type": "string"}}},
            read_only=False,
        ),
        make_tool(
            "update_ticket",
            "Update an incident ticket.",
            schema={"type": "object", "properties": {"id": {"type": "string"}}},
            read_only=False,
        ),
        make_tool(
            "restart_service",
            "Restart a service.",
            {"type": "object", "properties": {"service": {"type": "string"}}},
            read_only=False,
            destructive=True,
        ),
        make_tool(
            "delete_namespace",
            "Delete a namespace.",
            {"type": "object", "properties": {"namespace": {"type": "string"}}},
            read_only=False,
            destructive=True,
        ),
    ]
    while len(tools) < count:
        index = len(tools)
        tools.append(make_tool(f"extra_tool_{index:02d}", f"Extra test tool {index}."))
    return tools


class FakeUpstream:
    """In-process upstream implementing the gateway's upstream protocol."""

    def __init__(
        self,
        name: str,
        tools: list[Tool] | None = None,
        *,
        delay_s: float = 0.0,
        fail_times: int = 0,
        output_size: int = 20,
    ) -> None:
        self.name = name
        self.tools = tools if tools is not None else demo_tools()
        self.delay_s = delay_s
        self.fail_times = fail_times
        self.output_size = output_size
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.started = False
        self.stopped = False
        self.cancelled = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def list_tools(self) -> list[Tool]:
        return self.tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> CallToolResult:
        self.calls.append((name, arguments))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise OSError("transient upstream failure")
        if progress_callback is not None:
            await progress_callback(1, 1, "done")
        try:
            await asyncio.sleep(self.delay_s)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        text = "x" * self.output_size
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structuredContent={"result": text},
        )
