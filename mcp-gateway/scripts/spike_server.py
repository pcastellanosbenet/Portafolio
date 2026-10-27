"""Spike server used to validate the MCP 2026-07-28 behaviour before building the gateway."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.caching import CacheHint
from mcp.server.mcpserver import AcceptedElicitation, Context, Elicit, ElicitationResult, Resolve
from pydantic import BaseModel

mcp = MCPServer(
    name="spike-server",
    title="MCP spike server",
    version="0.1.0",
    instructions="Server used to verify protocol behaviour during phase 0.",
    cache_hints={"tools/list": CacheHint(ttl_ms=60_000, scope="public")},
)


class Approval(BaseModel):
    """Answer expected from the user before a destructive action."""

    approve: bool


async def ask_approval() -> Elicit[Approval]:
    """Ask the client for explicit approval."""
    return Elicit("Approve the destructive action?", Approval)


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@mcp.tool()
async def slow_task(seconds: float, ctx: Context) -> str:
    """Sleep for a while while reporting progress."""
    steps = 4
    for step in range(1, steps + 1):
        await asyncio.sleep(seconds / steps)
        await ctx.report_progress(step, steps, f"step {step}/{steps}")
    return f"slept {seconds}s"


@mcp.tool()
async def approve_action(
    action: str,
    approval: Annotated[ElicitationResult[Approval], Resolve(ask_approval)],
) -> str:
    """Perform an action only after the client approves it."""
    if isinstance(approval, AcceptedElicitation) and approval.data.approve:
        return f"approved: {action}"
    return f"rejected: {action}"


@mcp.tool()
async def cancel_probe(seconds: float = 5.0) -> str:
    """Sleep and write a marker on exit so tests can verify cancellation."""
    marker = Path(os.environ.get("SPIKE_CANCEL_MARKER", "/tmp/mcp-gateway-cancelled"))
    try:
        await asyncio.sleep(seconds)
        return "finished"
    finally:
        marker.write_text("cancelled", encoding="utf-8")


def extra_tool() -> str:
    """Tool added at runtime to exercise list-changed notifications."""
    return "extra"


@mcp.tool()
async def refresh_tools(ctx: Context) -> str:
    """Publish a tools/list_changed notification."""
    if "extra_tool" not in {tool.name for tool in await mcp.list_tools()}:
        mcp.add_tool(extra_tool)
    await ctx.notify_tools_changed()
    return "tools refreshed"


@mcp.resource("spike://info")
def info() -> str:
    """Return a small resource used to verify resources/read."""
    return "spike resource"


@mcp.prompt()
def review(text: str) -> str:
    """Return a prompt used to verify prompts/get."""
    return f"Review this text:\n\n{text}"


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.run(
            transport="streamable-http",
            host=os.environ.get("MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("MCP_PORT", "8765")),
        )
    else:
        mcp.run(transport="stdio")
