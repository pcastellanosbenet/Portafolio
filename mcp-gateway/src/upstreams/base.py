"""Upstream abstraction shared by real MCP servers and test doubles."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from mcp.types import CallToolResult, Tool

ProgressCallback = Callable[[float, float | None, str | None], Awaitable[None]]


@dataclass(frozen=True)
class UpstreamConfig:
    """How to reach one upstream MCP server."""

    name: str
    url: str | None = None
    command: str | None = None
    cwd: str | None = None

    def __post_init__(self) -> None:
        if bool(self.url) == bool(self.command):
            raise ValueError("an upstream needs exactly one of url or command")


class Upstream(Protocol):
    """Minimal upstream surface required by the gateway."""

    name: str

    async def start(self) -> None:
        """Connect to the upstream."""

    async def stop(self) -> None:
        """Close the connection."""

    async def list_tools(self) -> list[Tool]:
        """Return the upstream tool definitions."""

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> CallToolResult:
        """Call an upstream tool."""
