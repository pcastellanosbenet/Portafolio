"""Gateway MCP server: catalog, execution and auditing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from typing import Any

from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from mcp.server.caching import CacheHint
from mcp.types import (
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
)

from src.config import Settings
from src.gateway.audit import AuditLog
from src.gateway.catalog import Catalog, CatalogError
from src.gateway.executor import ToolExecutor
from src.gateway.integrity import suspicious_reason
from src.gateway.policy import PolicyEngine
from src.gateway.router import (
    FIND_TOOLS_NAME,
    INVOKE_TOOL_NAME,
    MODE_HYBRID,
    MODE_META,
    QUERY_META_KEY,
    ToolRouter,
    find_tools_payload,
)
from src.models import CallRecord, ToolDescriptor, arguments_hash, error_result
from src.upstreams.base import Upstream

logger = logging.getLogger(__name__)

CLIENT_INFO_KEY = "io.modelcontextprotocol/clientInfo"
APPROVAL_KEY = "approval"


class Gateway:
    """Aggregate upstream tools behind one MCP server."""

    def __init__(
        self,
        settings: Settings,
        upstreams: dict[str, Upstream],
        audit: AuditLog | None = None,
        policy: PolicyEngine | None = None,
    ) -> None:
        self.settings = settings
        self.upstreams = upstreams
        self.catalog = Catalog()
        self.audit = audit or AuditLog(settings.gateway_db_path)
        self.policy = policy or PolicyEngine(
            settings.gateway_approval_mode,
            allowlist=settings.allowlist,
            required_scope=settings.gateway_required_scope or None,
            granted_scopes=settings.granted_scopes,
        )
        self.executor = ToolExecutor(upstreams, settings, self.audit, self.policy)
        self.router = ToolRouter(settings.gateway_router_mode, settings.gateway_top_k)
        self.errors: dict[str, str] = {}
        self.quarantined: dict[str, str] = {}
        self._started = False
        self._approval_key = (
            settings.gateway_approval_secret or secrets.token_urlsafe(32)
        ).encode("utf-8")

    async def start(self) -> None:
        """Connect every upstream, tolerating individual failures."""
        if self._started:
            return
        for name, upstream in self.upstreams.items():
            try:
                await upstream.start()
                tools = await upstream.list_tools()
                safe_tools = []
                for tool in tools:
                    reason = suspicious_reason(tool)
                    if reason:
                        self.quarantined[f"{name}__{tool.name}"] = reason
                    else:
                        safe_tools.append(tool)
                self.catalog.register(name, safe_tools)
                self.errors.pop(name, None)
            except Exception as exc:  # noqa: BLE001 - one upstream must not kill the gateway
                self.errors[name] = f"{type(exc).__name__}: {exc}"
                logger.warning("upstream %s unavailable: %s", name, exc)
        self._started = True

    async def stop(self) -> None:
        """Close upstream connections and the audit log."""
        # MCP clients nest anyio cancel scopes, so they must close in reverse order.
        for upstream in reversed(list(self.upstreams.values())):
            try:
                await upstream.stop()
            except Exception:  # noqa: BLE001 - shutdown must be best effort
                logger.exception("failed to stop upstream %s", upstream.name)
        self.audit.close()
        self._started = False

    async def refresh(self, name: str) -> list[str]:
        """Refresh one upstream's tools and return the canonical names."""
        upstream = self.upstreams.get(name)
        if upstream is None:
            raise KeyError(f"unknown upstream: {name}")
        tools = await upstream.list_tools()
        for key in list(self.quarantined):
            if key.startswith(f"{name}__"):
                del self.quarantined[key]
        safe_tools = []
        for tool in tools:
            reason = suspicious_reason(tool)
            if reason:
                self.quarantined[f"{name}__{tool.name}"] = reason
            else:
                safe_tools.append(tool)
        try:
            descriptors = self.catalog.replace(name, safe_tools)
        except CatalogError as exc:
            self.errors[name] = str(exc)
            raise
        self.errors.pop(name, None)
        return [descriptor.name for descriptor in descriptors]

    def health(self) -> dict[str, Any]:
        """Return a small health snapshot for the HTTP endpoint."""
        return {
            "status": "ok" if not self.errors else "degraded",
            "protocol_version": "2026-07-28",
            "router_mode": self.router.mode,
            "top_k": self.router.top_k,
            "upstreams": {
                name: {
                    "connected": name not in self.errors,
                    "tools": len(self.catalog.by_server().get(name, [])),
                    "error": self.errors.get(name),
                }
                for name in self.upstreams
            },
            "tools": len(self.catalog),
            "quarantined": dict(sorted(self.quarantined.items())),
        }

    async def _list_tools(
        self,
        ctx: ServerRequestContext[Any, Any],
        _params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        query = None
        if ctx.meta:
            raw_query = ctx.meta.get(QUERY_META_KEY)
            if isinstance(raw_query, str):
                query = raw_query
        decision = self.router.route(query, self.catalog.descriptors())
        query_scoped = decision.mode == MODE_HYBRID and bool(query)
        return ListToolsResult(
            tools=decision.tools,
            ttlMs=0 if query_scoped else 60_000,
            cacheScope="private" if query_scoped else "public",
        )

    async def _call_tool(
        self,
        ctx: ServerRequestContext[Any, Any],
        params: CallToolRequestParams,
    ) -> CallToolResult | InputRequiredResult:
        if params.name == FIND_TOOLS_NAME:
            return self._find_tools(params.arguments or {})
        if params.name == INVOKE_TOOL_NAME:
            return await self._invoke_tool(ctx, params)

        descriptor = self.catalog.get(params.name)
        if descriptor is None:
            raise MCPError(INVALID_PARAMS, f"Unknown tool: {params.name}")
        if self.router.mode == MODE_META:
            raise MCPError(
                INVALID_PARAMS,
                f"Tool {params.name} is not exposed in meta mode; use invoke_tool",
            )
        return await self._call_descriptor(
            ctx,
            descriptor,
            params.arguments or {},
            request_state=params.request_state,
            input_responses=params.input_responses,
        )

    def _find_tools(self, arguments: dict[str, Any]) -> CallToolResult:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return error_result("find_tools requires a non-empty query string")
        raw_limit = arguments.get("limit", self.settings.gateway_top_k)
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            return error_result("find_tools limit must be an integer")
        payload = find_tools_payload(
            self.router, query.strip(), self.catalog.descriptors(), limit
        )
        trace_id = uuid.uuid4().hex
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
            structuredContent=payload,
            meta={"trace_id": trace_id},
        )

    async def _invoke_tool(
        self,
        ctx: ServerRequestContext[Any, Any],
        params: CallToolRequestParams,
    ) -> CallToolResult | InputRequiredResult:
        arguments = params.arguments or {}
        server = arguments.get("server")
        tool = arguments.get("tool")
        tool_arguments = arguments.get("arguments", {})
        if not isinstance(server, str) or not server.strip():
            return error_result("invoke_tool requires a non-empty server")
        if not isinstance(tool, str) or not tool.strip():
            return error_result("invoke_tool requires a non-empty tool")
        if not isinstance(tool_arguments, dict):
            return error_result("invoke_tool arguments must be a JSON object")

        server_name = server.strip().removesuffix("-mcp")
        name = tool.strip()
        if "__" not in name:
            name = f"{server_name}__{name}"
        descriptor = self.catalog.get(name)
        if descriptor is None:
            return error_result(f"unknown upstream tool: {server_name}__{tool}")
        return await self._call_descriptor(
            ctx,
            descriptor,
            tool_arguments,
            request_state=params.request_state,
            input_responses=params.input_responses,
        )

    async def _call_descriptor(
        self,
        ctx: ServerRequestContext[Any, Any],
        descriptor: ToolDescriptor,
        arguments: dict[str, Any],
        *,
        request_state: str | None,
        input_responses: dict[str, Any] | None,
    ) -> CallToolResult | InputRequiredResult:
        client = (ctx.meta or {}).get(CLIENT_INFO_KEY) or {}
        client_name = client.get("name", "unknown") if isinstance(client, dict) else "unknown"
        trace_id = uuid.uuid4().hex
        approval_granted = False

        decision = self.policy.evaluate(descriptor)
        if decision.approval_required:
            if not request_state and not input_responses:
                self.audit.record(
                    CallRecord(
                        trace_id=trace_id,
                        server=descriptor.server,
                        tool=descriptor.name,
                        status="approval_pending",
                        latency_ms=0.0,
                        protocol_version=ctx.protocol_version,
                        client_name=client_name,
                        arguments_hash=arguments_hash(arguments),
                        error="waiting for approval",
                    )
                )
                return self._approval_request(descriptor, arguments, trace_id)

            approved, reason, approved_trace = self._approval_answer(
                descriptor, arguments, request_state, input_responses
            )
            if approved_trace:
                trace_id = approved_trace
            if not approved:
                self.audit.record(
                    CallRecord(
                        trace_id=trace_id,
                        server=descriptor.server,
                        tool=descriptor.name,
                        status="approval_denied",
                        latency_ms=0.0,
                        protocol_version=ctx.protocol_version,
                        client_name=client_name,
                        arguments_hash=arguments_hash(arguments),
                        error=reason,
                    )
                )
                denied = error_result(f"approval denied: {reason}")
                denied.meta = {"trace_id": trace_id}
                return denied
            approval_granted = True

        async def forward_progress(
            progress: float, total: float | None, message: str | None
        ) -> None:
            await ctx.session.report_progress(progress, total, message)

        execution = await self.executor.execute(
            descriptor,
            arguments,
            trace_id=trace_id,
            protocol_version=ctx.protocol_version,
            client_name=client_name,
            progress_callback=forward_progress,
            approval_granted=approval_granted,
        )
        result = execution.result
        result.meta = {**(result.meta or {}), "trace_id": trace_id}
        return result

    def _seal_state(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self._approval_key, raw, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(raw + signature).decode("ascii")

    def _open_state(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        try:
            decoded = base64.urlsafe_b64decode(token.encode("ascii"))
            if len(decoded) <= 32:
                return None
            raw, signature = decoded[:-32], decoded[-32:]
            expected = hmac.new(self._approval_key, raw, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                return None
            payload = json.loads(raw)
            if int(payload.get("exp", 0)) < int(time.time()):
                return None
            return payload
        except (ValueError, TypeError):
            return None

    def _approval_request(
        self,
        descriptor: ToolDescriptor,
        arguments: dict[str, Any],
        trace_id: str,
    ) -> InputRequiredResult:
        state = self._seal_state(
            {
                "trace_id": trace_id,
                "tool": descriptor.name,
                "definition": descriptor.definition_hash,
                "args": arguments_hash(arguments),
                "exp": int(time.time()) + self.settings.gateway_approval_ttl_s,
            }
        )
        request = ElicitRequest(
            params=ElicitRequestFormParams(
                message=(
                    f"Approve {descriptor.name}? The gateway classifies this tool "
                    "as destructive."
                ),
                requested_schema={
                    "type": "object",
                    "properties": {
                        "approve": {
                            "type": "boolean",
                            "title": "Approve",
                            "description": "Allow this destructive call once.",
                        }
                    },
                    "required": ["approve"],
                },
            )
        )
        return InputRequiredResult(
            input_requests={APPROVAL_KEY: request},
            request_state=state,
        )

    def _approval_answer(
        self,
        descriptor: ToolDescriptor,
        arguments: dict[str, Any],
        request_state: str | None,
        input_responses: dict[str, Any] | None,
    ) -> tuple[bool, str, str | None]:
        payload = self._open_state(request_state)
        if payload is None:
            return False, "invalid or expired request state", None
        if (
            payload.get("tool") != descriptor.name
            or payload.get("definition") != descriptor.definition_hash
            or payload.get("args") != arguments_hash(arguments)
        ):
            return False, "approval state does not match this call", payload.get("trace_id")

        response = (input_responses or {}).get(APPROVAL_KEY)
        if isinstance(response, ElicitResult):
            action = response.action
            content = response.content or {}
        elif isinstance(response, dict):
            action = response.get("action")
            content = response.get("content") or {}
        else:
            return False, "missing approval response", payload.get("trace_id")

        approved = action == "accept" and content.get("approve") is True
        reason = "approved" if approved else "the user did not approve the call"
        return approved, reason, payload.get("trace_id")

    def build_server(self) -> Server:
        """Build the low-level MCP server that exposes the catalog."""
        cache_hints = None
        if self.router.mode != MODE_HYBRID:
            cache_hints = {"tools/list": CacheHint(ttl_ms=60_000, scope="public")}
        return Server(
            name="mcp-gateway",
            title="MCP Gateway",
            version="0.1.0",
            instructions=(
                "Aggregated MCP tools. Names are namespaced as server__tool. "
                "Destructive tools require explicit approval. Router mode: "
                f"{self.router.mode}."
            ),
            cache_hints=cache_hints,
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )
