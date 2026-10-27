"""ops-mcp: a synthetic HTTP MCP server with 12 operational tools."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.upstreams.ops.state import OpsState

READ_ONLY = ToolAnnotations(readOnlyHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)

state = OpsState()


def _call[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a state operation and turn expected errors into tool errors."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

mcp = MCPServer(
    name="ops-mcp",
    title="Ops MCP",
    version="0.1.0",
    instructions=(
        "Synthetic operations tools. Reads are safe; writes mutate in-memory state; "
        "restart_service and delete_namespace are destructive."
    ),
)


@mcp.tool(annotations=READ_ONLY)
def list_services() -> dict[str, Any]:
    """List every synthetic service and its current state."""
    services = state.list_services()
    return {"count": len(services), "services": services}


@mcp.tool(annotations=READ_ONLY)
def get_service(service: str) -> dict[str, Any]:
    """Return one service by name."""
    return _call(state.get_service, service)


@mcp.tool(annotations=READ_ONLY)
def query_metrics(service: str, window_minutes: int = 15) -> dict[str, Any]:
    """Return a deterministic latency and error-rate series."""
    return _call(state.query_metrics, service, window_minutes)


@mcp.tool(annotations=READ_ONLY)
def list_incidents(status: str | None = None) -> dict[str, Any]:
    """List incidents, optionally filtered by open, acknowledged or resolved."""
    incidents = _call(state.list_incidents, status)
    return {"count": len(incidents), "incidents": incidents}


@mcp.tool(annotations=READ_ONLY)
def get_incident(incident_id: str) -> dict[str, Any]:
    """Return one incident by id."""
    return _call(state.get_incident, incident_id)


@mcp.tool(annotations=READ_ONLY)
def search_logs(service: str, query: str = "", limit: int = 10) -> dict[str, Any]:
    """Search recent synthetic logs for a service."""
    return _call(state.search_logs, service, query, limit)


@mcp.tool(annotations=READ_ONLY)
def deploy_history(service: str, limit: int = 5) -> dict[str, Any]:
    """Return recent deploys for a service."""
    return _call(state.deploy_history, service, limit)


@mcp.tool(annotations=WRITE)
def create_incident(title: str, service: str, severity: str) -> dict[str, Any]:
    """Create an incident with severity sev1, sev2 or sev3."""
    return _call(state.create_incident, title, service, severity)


@mcp.tool(annotations=WRITE)
def update_incident(incident_id: str, status: str) -> dict[str, Any]:
    """Change an incident status to open, acknowledged or resolved."""
    return _call(state.update_incident, incident_id, status)


@mcp.tool(annotations=WRITE)
def ack_incident(incident_id: str) -> dict[str, Any]:
    """Acknowledge an incident."""
    return _call(state.ack_incident, incident_id)


@mcp.tool(annotations=DESTRUCTIVE)
def restart_service(service: str) -> dict[str, Any]:
    """Restart a service. This is a destructive action and needs approval."""
    return _call(state.restart_service, service)


@mcp.tool(annotations=DESTRUCTIVE)
def delete_namespace(namespace: str) -> dict[str, Any]:
    """Delete a namespace. This is destructive and needs approval."""
    return _call(state.delete_namespace, namespace)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    """Expose a small health check for Docker Compose."""
    return JSONResponse({"status": "ok", "services": len(state.services)})


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=os.environ.get("MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("MCP_PORT", "8767")),
    )
