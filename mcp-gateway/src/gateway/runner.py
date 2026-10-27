"""Run the gateway over stdio or Streamable HTTP."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from mcp.server.stdio import stdio_server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from src.config import Settings
from src.gateway.auth import BearerAuthMiddleware
from src.gateway.server import Gateway
from src.upstreams.base import Upstream, UpstreamConfig
from src.upstreams.mcp import MCPUpstream

ROOT = Path(__file__).resolve().parents[2]


def build_upstreams(settings: Settings) -> dict[str, Upstream]:
    """Build upstream clients from configuration."""
    upstreams: dict[str, Upstream] = {}
    for name in settings.upstream_names:
        if name == "docs":
            config = UpstreamConfig(name, url=settings.docs_mcp_url)
        elif name == "ops":
            config = UpstreamConfig(name, url=settings.ops_mcp_url)
        elif name == "research":
            config = UpstreamConfig(
                name,
                command=settings.research_mcp_command,
                cwd=str(ROOT),
            )
        else:
            raise ValueError(f"unknown upstream in GATEWAY_UPSTREAMS: {name}")
        upstreams[name] = MCPUpstream(config, timeout_s=settings.gateway_upstream_timeout_s)
    return upstreams


def build_gateway(settings: Settings) -> Gateway:
    """Build a gateway with the configured upstreams."""
    return Gateway(settings, build_upstreams(settings))


def build_http_app(gateway: Gateway, *, manage_gateway: bool = True):
    """Build the Streamable HTTP app, including health and PRM routes."""
    settings = gateway.settings
    server = gateway.build_server()

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse(gateway.health())

    async def protected_resource(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "resource": settings.gateway_public_url,
                "authorization_servers": [],
                "scopes_supported": settings.scopes_supported,
                "bearer_methods_supported": ["header"],
            }
        )

    allowed_origins = settings.allowed_origins or [
        "http://127.0.0.1:*",
        "http://localhost:*",
    ]
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=allowed_origins,
    )
    app = server.streamable_http_app(
        host=settings.gateway_host,
        transport_security=transport_security,
        custom_starlette_routes=[
            Route("/health", health),
            Route("/.well-known/oauth-protected-resource", protected_resource),
        ],
    )

    base_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application) -> AsyncIterator[None]:
        if manage_gateway:
            await gateway.start()
        try:
            async with base_lifespan(application):
                yield
        finally:
            if manage_gateway:
                await gateway.stop()

    app.router.lifespan_context = lifespan
    if settings.gateway_auth_mode == "bearer":
        if not settings.gateway_token:
            raise ValueError("GATEWAY_AUTH_MODE=bearer requires GATEWAY_TOKEN")
        metadata_url = (
            settings.gateway_public_url.rsplit("/mcp", 1)[0]
            + "/.well-known/oauth-protected-resource"
        )
        return BearerAuthMiddleware(app, settings.gateway_token, metadata_url)
    return app


async def run_http(gateway: Gateway) -> None:
    """Serve the gateway over Streamable HTTP until cancelled."""
    app = build_http_app(gateway)
    config = uvicorn.Config(
        app,
        host=gateway.settings.gateway_host,
        port=gateway.settings.gateway_port,
        log_level="info",
    )
    await uvicorn.Server(config).serve()


async def run_stdio(gateway: Gateway) -> None:
    """Serve the gateway over stdio until the client disconnects."""
    await gateway.start()
    try:
        server = gateway.build_server()
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        await gateway.stop()
