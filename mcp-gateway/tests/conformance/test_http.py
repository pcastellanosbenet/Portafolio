"""Protocol conformance checks over Streamable HTTP."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx
import pytest
import uvicorn

from src.config import Settings
from src.gateway.audit import AuditLog
from src.gateway.policy import PolicyEngine
from src.gateway.runner import build_http_app
from src.gateway.server import Gateway
from tests.fakes import FakeUpstream

PROTOCOL = "2026-07-28"


@pytest.fixture(scope="module")
def http_server():
    settings = Settings(
        gateway_host="127.0.0.1",
        gateway_db_path=":memory:",
        gateway_approval_mode="auto",
        gateway_allowed_origins="http://127.0.0.1:*",
        gateway_router_mode="static",
    )
    gateway = Gateway(
        settings,
        {"docs": FakeUpstream("docs")},
        audit=AuditLog(":memory:"),
        policy=PolicyEngine("auto"),
    )
    app = build_http_app(gateway)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def rpc(
    url: str,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    version: str = PROTOCOL,
    mcp_name: str | None = None,
    origin: str | None = None,
) -> httpx.Response:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": version,
        "Mcp-Method": method,
    }
    if mcp_name is not None:
        headers["Mcp-Name"] = mcp_name
    if origin is not None:
        headers["Origin"] = origin
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            **(params or {}),
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": version,
                "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "0"},
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
    }
    return httpx.post(f"{url}/mcp", headers=headers, json=body, timeout=10)


def test_server_discover(http_server: str) -> None:
    response = rpc(http_server, "server/discover")
    assert response.status_code == 200
    result = response.json()["result"]
    assert PROTOCOL in result["supportedVersions"]
    assert result["resultType"] == "complete"


def test_tools_list_is_deterministic_and_cacheable(http_server: str) -> None:
    first = rpc(http_server, "tools/list").json()["result"]
    second = rpc(http_server, "tools/list").json()["result"]
    names = [tool["name"] for tool in first["tools"]]
    assert names == [tool["name"] for tool in second["tools"]]
    assert names == sorted(names)
    assert len(names) == 25
    assert first["ttlMs"] == 60_000
    assert first["cacheScope"] == "public"


def test_modern_requests_do_not_create_sessions(http_server: str) -> None:
    response = rpc(http_server, "tools/list")
    assert "mcp-session-id" not in {key.lower() for key in response.headers}


def test_tools_call_with_matching_headers(http_server: str) -> None:
    response = rpc(
        http_server,
        "tools/call",
        {"name": "docs__search_docs", "arguments": {"query": "mcp"}},
        mcp_name="docs__search_docs",
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False
    assert result["resultType"] == "complete"


def test_header_mismatch_is_rejected(http_server: str) -> None:
    response = rpc(
        http_server,
        "tools/call",
        {"name": "docs__search_docs", "arguments": {"query": "mcp"}},
        mcp_name="docs__other",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32020


def test_unsupported_version_is_rejected(http_server: str) -> None:
    response = rpc(http_server, "tools/list", version="2027-01-01")
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == -32022
    assert error["data"]["supported"] == [PROTOCOL]


def test_get_and_delete_are_rejected(http_server: str) -> None:
    for method in ("GET", "DELETE"):
        response = httpx.request(
            method,
            f"{http_server}/mcp",
            headers={"MCP-Protocol-Version": PROTOCOL},
            timeout=10,
        )
        assert response.status_code == 405
        assert response.headers["allow"] == "POST"


def test_invalid_origin_is_rejected(http_server: str) -> None:
    response = rpc(http_server, "tools/list", origin="http://evil.example")
    assert response.status_code == 403


def test_unknown_method_returns_method_not_found(http_server: str) -> None:
    response = rpc(http_server, "does/not/exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == -32601


def test_health_endpoint(http_server: str) -> None:
    response = httpx.get(f"{http_server}/health", timeout=10)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["tools"] == 25
