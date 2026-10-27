"""Integration test against the three real upstreams over HTTP and stdio."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import uvicorn
from mcp import Client
from mcp.server.transport_security import TransportSecuritySettings

from src.config import Settings
from src.gateway.audit import AuditLog
from src.gateway.policy import PolicyEngine
from src.gateway.runner import build_upstreams
from src.gateway.server import Gateway
from src.upstreams.docs.server import mcp as docs_server
from src.upstreams.ops.server import mcp as ops_server

ROOT = Path(__file__).resolve().parents[2]


class AppServer:
    """Run one Starlette app in a background thread on an ephemeral port."""

    def __init__(self, app) -> None:
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("upstream server did not start")
            time.sleep(0.01)
        socket = self.server.servers[0].sockets[0]
        port = socket.getsockname()[1]
        return f"http://127.0.0.1:{port}/mcp"

    def __exit__(self, *_exc_info) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


async def test_gateway_aggregates_three_real_upstreams() -> None:
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    docs_app = docs_server.streamable_http_app(transport_security=security)
    ops_app = ops_server.streamable_http_app(transport_security=security)

    with AppServer(docs_app) as docs_url, AppServer(ops_app) as ops_url:
        settings = Settings(
            gateway_db_path=":memory:",
            gateway_upstreams="docs,research,ops",
            docs_mcp_url=docs_url,
            ops_mcp_url=ops_url,
            research_mcp_command=(
                f"{sys.executable} -m src.upstreams.research.server"
            ),
            gateway_max_retries=0,
            gateway_upstream_timeout_s=5.0,
            gateway_router_mode="static",
        )
        gateway = Gateway(
            settings,
            build_upstreams(settings),
            audit=AuditLog(":memory:"),
            policy=PolicyEngine("auto"),
        )
        await gateway.start()
        try:
            assert gateway.health()["tools"] == 22
            async with Client(gateway.build_server()) as client:
                docs = await client.call_tool("docs__list_docs", {})
                assert docs.structured_content["count"] == 5

                ops = await client.call_tool("ops__list_services", {})
                assert ops.structured_content["count"] == 5

                research = await client.call_tool(
                    "research__wikipedia_search", {"query": "SSRF"}
                )
                assert research.structured_content["mode"] == "fixtures"
                assert research.structured_content["results"][0]["id"] == "ssrf"
        finally:
            await gateway.stop()
