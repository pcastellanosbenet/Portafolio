"""Start docs-mcp and ops-mcp on ephemeral HTTP ports for local evaluation."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings

from src.upstreams.docs.server import mcp as docs_server
from src.upstreams.ops.server import mcp as ops_server


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


@contextmanager
def local_upstreams() -> Iterator[tuple[str, str]]:
    """Yield the docs and ops MCP URLs, shutting both servers down afterwards."""
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    docs_app = docs_server.streamable_http_app(transport_security=security)
    ops_app = ops_server.streamable_http_app(transport_security=security)
    with AppServer(docs_app) as docs_url, AppServer(ops_app) as ops_url:
        yield docs_url, ops_url
