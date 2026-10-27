"""Domain models for the MCP gateway."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from mcp.types import CallToolResult, TextContent, Tool

NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class RiskLevel(StrEnum):
    """Risk classification used by the policy engine."""

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ToolDescriptor:
    """An upstream tool with the canonical name exposed by the gateway."""

    server: str
    original_name: str
    name: str
    tool: Tool
    risk: RiskLevel
    definition_hash: str


@dataclass(frozen=True)
class CallRecord:
    """One tool call, as persisted by the audit log."""

    trace_id: str
    server: str
    tool: str
    status: str
    latency_ms: float
    protocol_version: str
    client_name: str
    arguments_hash: str
    error: str | None = None


def namespaced_name(server: str, tool: str) -> str:
    """Return the canonical `server__tool` name, validating client-safe characters."""
    name = f"{server}__{tool}"
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError(
            f"invalid tool name {name!r}: expected 1-64 characters from [A-Za-z0-9_-]"
        )
    return name


def infer_risk(tool: Tool) -> RiskLevel:
    """Infer a conservative risk level from MCP tool annotations."""
    annotations = tool.annotations
    if annotations is not None:
        if annotations.destructive_hint:
            return RiskLevel.DESTRUCTIVE
        if annotations.read_only_hint:
            return RiskLevel.READ
    return RiskLevel.WRITE


def definition_hash(tool: Tool) -> str:
    """Return a stable SHA-256 hash of a tool definition."""
    payload = json.dumps(
        tool.model_dump(mode="json", by_alias=True, exclude_none=True),
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_descriptor(server: str, tool: Tool) -> ToolDescriptor:
    """Build a descriptor for an upstream tool under its namespaced name."""
    name = namespaced_name(server, tool.name)
    exposed = tool.model_copy(update={"name": name})
    return ToolDescriptor(
        server=server,
        original_name=tool.name,
        name=name,
        tool=exposed,
        risk=infer_risk(tool),
        definition_hash=definition_hash(exposed),
    )


def error_result(message: str) -> CallToolResult:
    """Return a tool-level error that the model can read and react to."""
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        isError=True,
    )


def arguments_hash(arguments: dict[str, Any]) -> str:
    """Return a stable hash of call arguments for audit purposes."""
    payload = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
