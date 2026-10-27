"""Tool execution with validation, timeouts, retries, limits and auditing."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import jsonschema
from mcp.types import CallToolResult, TextContent

from src.config import Settings
from src.gateway.audit import AuditLog
from src.gateway.policy import PolicyEngine
from src.models import CallRecord, ToolDescriptor, arguments_hash, error_result
from src.upstreams.base import ProgressCallback, Upstream


@dataclass
class ExecutionResult:
    """Result of one gateway call plus local timing metadata."""

    result: CallToolResult
    latency_ms: float
    attempts: int
    truncated: bool = False


class ToolExecutor:
    """Execute catalog tools against their upstreams."""

    def __init__(
        self,
        upstreams: dict[str, Upstream],
        settings: Settings,
        audit: AuditLog,
        policy: PolicyEngine,
    ) -> None:
        self.upstreams = upstreams
        self.settings = settings
        self.audit = audit
        self.policy = policy

    async def execute(
        self,
        descriptor: ToolDescriptor,
        arguments: dict[str, Any],
        *,
        trace_id: str,
        protocol_version: str = "unknown",
        client_name: str = "unknown",
        progress_callback: ProgressCallback | None = None,
        approval_granted: bool = False,
    ) -> ExecutionResult:
        """Validate, authorize and execute one call, auditing every outcome."""
        started = time.perf_counter()

        def finish(
            result: CallToolResult, status: str, attempts: int = 0, truncated: bool = False
        ) -> ExecutionResult:
            latency = (time.perf_counter() - started) * 1000
            self.audit.record(
                CallRecord(
                    trace_id=trace_id,
                    server=descriptor.server,
                    tool=descriptor.name,
                    status=status,
                    latency_ms=round(latency, 2),
                    protocol_version=protocol_version,
                    client_name=client_name,
                    arguments_hash=arguments_hash(arguments),
                    error=result.content[0].text if result.is_error and result.content else None,
                )
            )
            return ExecutionResult(
                result=result, latency_ms=latency, attempts=attempts, truncated=truncated
            )

        decision = self.policy.evaluate(descriptor)
        if not decision.allowed:
            return finish(error_result(f"policy denied: {decision.reason}"), "policy_denied")
        if decision.approval_required and not approval_granted:
            return finish(
                error_result(
                    "approval required: this build of the gateway does not implement "
                    f"elicitation yet ({decision.reason})"
                ),
                "approval_required",
            )

        try:
            jsonschema.Draft202012Validator(descriptor.tool.input_schema).validate(arguments)
        except jsonschema.ValidationError as exc:
            return finish(
                error_result(f"invalid arguments for {descriptor.name}: {exc.message}"),
                "invalid_arguments",
            )

        upstream = self.upstreams[descriptor.server]
        attempts = 0
        last_error: Exception | None = None
        for attempt in range(1, self.settings.gateway_max_retries + 2):
            attempts = attempt
            try:
                async with asyncio.timeout(self.settings.gateway_upstream_timeout_s):
                    result = await upstream.call_tool(
                        descriptor.original_name,
                        arguments,
                        progress_callback=progress_callback,
                    )
                limited, truncated = enforce_output_limit(
                    result, self.settings.gateway_max_output_bytes
                )
                return finish(limited, "ok", attempts, truncated)
            except TimeoutError as exc:
                last_error = exc
            except (OSError, ConnectionError) as exc:
                last_error = exc
            except Exception as exc:  # noqa: BLE001 - upstream errors are reported to the model
                last_error = exc
                break

        message = f"upstream call failed: {type(last_error).__name__}: {last_error}"
        return finish(error_result(message), "error", attempts)


def enforce_output_limit(result: CallToolResult, max_bytes: int) -> tuple[CallToolResult, bool]:
    """Truncate oversized text output so it cannot flood the model context."""
    serialized = result.model_dump_json()
    if len(serialized.encode("utf-8")) <= max_bytes:
        return result, False

    budget = max(256, max_bytes - 128)
    content: list[TextContent] = []
    used = 0
    for item in result.content:
        if item.type != "text":
            continue
        remaining = budget - used
        if remaining <= 0:
            break
        text = item.text[:remaining]
        content.append(TextContent(type="text", text=text))
        used += len(text.encode("utf-8"))

    content.append(TextContent(type="text", text="\n[output truncated by gateway]"))
    meta = dict(result.meta or {})
    meta["truncated"] = True
    return (
        CallToolResult(
            content=content,
            structuredContent=None,
            isError=result.is_error,
            meta=meta,
        ),
        True,
    )
