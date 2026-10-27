"""Minimal bearer-token guard for the Streamable HTTP endpoint."""

from __future__ import annotations

import hmac

from starlette.datastructures import Headers
from starlette.responses import JSONResponse


class BearerAuthMiddleware:
    """Reject requests without the configured bearer token.

    This is a lab resource-server check, not an OAuth authorization server.
    """

    def __init__(self, app, token: str, resource_metadata_url: str) -> None:
        self.app = app
        self.token = token
        self.resource_metadata_url = resource_metadata_url

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/mcp":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        provided = headers.get("authorization", "")
        expected = f"Bearer {self.token}"
        if not hmac.compare_digest(provided, expected):
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer resource_metadata="' + self.resource_metadata_url + '"'
                    )
                },
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
