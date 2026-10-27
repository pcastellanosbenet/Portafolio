"""Redact common secrets before writing errors to audit logs."""

from __future__ import annotations

import re

REDACTIONS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-~+/]+=*"),
    re.compile(r"\b(gsk_|sk-)[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(token\s*[:=]\s*)[^\s,;]+"),
]


def redact(text: str | None) -> str | None:
    """Replace secret-looking values with a stable marker."""
    if not text:
        return text
    redacted = text
    for pattern in REDACTIONS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted
