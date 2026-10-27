"""research-mcp: stdio server for Wikipedia, arXiv and guarded URL fetches."""

from __future__ import annotations

import os
from collections.abc import Awaitable
from typing import Any

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from src.upstreams.research.sources import ResearchService
from src.upstreams.research.sources import fetch_url as fetch_public_url

READ_ONLY = ToolAnnotations(readOnlyHint=True)
service = ResearchService(os.environ.get("RESEARCH_MODE", "fixtures"))


async def _run[T](coro: Awaitable[T]) -> T:
    """Turn expected source failures into readable tool errors."""
    try:
        return await coro
    except (ValueError, httpx.HTTPError) as exc:
        raise ToolError(str(exc)) from exc

mcp = MCPServer(
    name="research-mcp",
    title="Research MCP",
    version="0.1.0",
    instructions=(
        "Search Wikipedia and arXiv. The default 'fixtures' mode is deterministic and "
        "offline; set RESEARCH_MODE=live for real network results. fetch_url blocks "
        "private addresses and non-HTTP schemes."
    ),
)


@mcp.tool(annotations=READ_ONLY)
async def wikipedia_search(query: str, limit: int = 5) -> dict[str, Any]:
    """Search Wikipedia (or the deterministic fixture corpus)."""
    return await _run(service.wikipedia_search(query, limit))


@mcp.tool(annotations=READ_ONLY)
async def wikipedia_get(title: str) -> dict[str, Any]:
    """Read a Wikipedia page summary."""
    return await _run(service.wikipedia_get(title))


@mcp.tool(annotations=READ_ONLY)
async def arxiv_search(query: str, limit: int = 5) -> dict[str, Any]:
    """Search arXiv (or the deterministic fixture corpus)."""
    return await _run(service.arxiv_search(query, limit))


@mcp.tool(annotations=READ_ONLY)
async def arxiv_get(arxiv_id: str) -> dict[str, Any]:
    """Read one arXiv paper by id."""
    return await _run(service.arxiv_get(arxiv_id))


@mcp.tool(name="fetch_url", annotations=READ_ONLY)
async def fetch_url_tool(url: str, max_chars: int = 4000) -> dict[str, Any]:
    """Fetch a public URL with SSRF protection and a size limit."""
    try:
        return await fetch_public_url(url, max_chars)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


if __name__ == "__main__":
    mcp.run(transport="stdio")
