"""Audit log for gateway tool calls."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, replace
from pathlib import Path

from src.gateway.redaction import redact
from src.models import CallRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    trace_id TEXT NOT NULL,
    server TEXT NOT NULL,
    tool TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    protocol_version TEXT NOT NULL,
    client_name TEXT NOT NULL,
    arguments_hash TEXT NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS calls_trace_id ON calls (trace_id);
CREATE INDEX IF NOT EXISTS calls_tool ON calls (tool);
"""


class AuditLog:
    """Persist call metadata to SQLite and, optionally, JSONL."""

    def __init__(self, db_path: str = ":memory:", jsonl_path: str | None = None) -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.executescript(SCHEMA)
        self._connection.commit()
        self._lock = threading.Lock()
        self._jsonl_path = Path(jsonl_path) if jsonl_path else None
        if self._jsonl_path is not None:
            self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, record: CallRecord) -> None:
        """Persist one call record, redacting secret-looking error text."""
        record = replace(record, error=redact(record.error))
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO calls (
                    trace_id, server, tool, status, latency_ms,
                    protocol_version, client_name, arguments_hash, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.trace_id,
                    record.server,
                    record.tool,
                    record.status,
                    record.latency_ms,
                    record.protocol_version,
                    record.client_name,
                    record.arguments_hash,
                    record.error,
                ),
            )
            self._connection.commit()
            if self._jsonl_path is not None:
                with self._jsonl_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def recent(self, limit: int = 50) -> list[dict[str, object]]:
        """Return the most recent records, newest first."""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT trace_id, server, tool, status, latency_ms,
                       protocol_version, client_name, arguments_hash, error, created_at
                FROM calls ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        columns = [
            "trace_id",
            "server",
            "tool",
            "status",
            "latency_ms",
            "protocol_version",
            "client_name",
            "arguments_hash",
            "error",
            "created_at",
        ]
        return [dict(zip(columns, row, strict=True)) for row in rows]

    def close(self) -> None:
        """Close the SQLite connection."""
        self._connection.close()
