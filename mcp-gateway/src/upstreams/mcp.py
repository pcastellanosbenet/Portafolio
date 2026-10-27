"""MCP client adapter for one upstream server."""

from __future__ import annotations

import shlex
from contextlib import AsyncExitStack
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.types import CallToolResult, Tool

from src.upstreams.base import ProgressCallback, UpstreamConfig

# Errors that suggest the connection is gone and a reconnect is worth trying.
TRANSPORT_ERRORS = (OSError, ConnectionError)


class MCPUpstream:
    """Persistent MCP client connection to one upstream."""

    def __init__(self, config: UpstreamConfig, timeout_s: float = 20.0) -> None:
        self.config = config
        self.name = config.name
        self.timeout_s = timeout_s
        self._client: Client | None = None
        self._stack: AsyncExitStack | None = None

    def _client_factory(self) -> Client:
        if self.config.url:
            return Client(self.config.url, read_timeout_seconds=self.timeout_s)
        command = shlex.split(self.config.command or "")
        if not command:
            raise ValueError(f"upstream {self.name} has an empty command")
        return Client(
            StdioServerParameters(
                command=command[0],
                args=command[1:],
                cwd=self.config.cwd,
            ),
            read_timeout_seconds=self.timeout_s,
        )

    async def start(self) -> None:
        """Open the MCP connection and keep it for subsequent calls."""
        if self._client is not None:
            return
        stack = AsyncExitStack()
        try:
            self._client = await stack.enter_async_context(self._client_factory())
        except Exception:
            await stack.aclose()
            raise
        self._stack = stack

    async def stop(self) -> None:
        """Close the MCP connection."""
        self._client = None
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None

    async def reconnect(self) -> None:
        """Drop the current connection and open a new one."""
        await self.stop()
        await self.start()

    def _require_client(self) -> Client:
        if self._client is None:
            raise RuntimeError(f"upstream {self.name} is not connected")
        return self._client

    async def list_tools(self) -> list[Tool]:
        """Return the upstream tool definitions."""
        result = await self._require_client().list_tools()
        return result.tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> CallToolResult:
        """Call one upstream tool, reconnecting once on a transport error."""
        client = self._require_client()
        try:
            return await client.call_tool(
                name, arguments, progress_callback=progress_callback
            )
        except TRANSPORT_ERRORS:
            await self.reconnect()
            raise
