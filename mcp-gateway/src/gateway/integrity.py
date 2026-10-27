"""Detect tool metadata that looks like an instruction injection."""

from __future__ import annotations

import re

from mcp.types import Tool

SUSPICIOUS_PATTERNS = [
    re.compile(r"ignore (all )?(previous|prior) instructions", re.IGNORECASE),
    re.compile(r"disregard (the )?(system|previous) prompt", re.IGNORECASE),
    re.compile(r"system prompt", re.IGNORECASE),
    re.compile(r"exfiltrat(e|ion)", re.IGNORECASE),
    re.compile(r"<script\b", re.IGNORECASE),
    re.compile(r"send (the )?(secret|token|api key)", re.IGNORECASE),
]


def suspicious_reason(tool: Tool) -> str | None:
    """Return a reason when a tool description contains instruction-like text."""
    text = f"{tool.name} {tool.description or ''}"
    for pattern in SUSPICIOUS_PATTERNS:
        match = pattern.search(text)
        if match:
            return f"suspicious metadata: {match.group(0)!r}"
    return None
