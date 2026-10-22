"""Small SQLite cache with TTL and deterministic keys."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class SQLiteCache:
    """Persistent JSON cache safe for sequential and thread-pool use."""

    def __init__(
        self,
        path: Path,
        *,
        default_ttl_s: int = 86_400,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.default_ttl_s = default_ttl_s
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            if str(self.path) != ":memory:":
                connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    cache_key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )

    @staticmethod
    def make_key(namespace: str, payload: Any) -> str:
        serialized = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return f"{namespace}:{digest}"

    def get_json(self, cache_key: str) -> Any | None:
        now = self._clock()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json, expires_at FROM cache_entries WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            value_json, expires_at = row
            if expires_at <= now:
                connection.execute(
                    "DELETE FROM cache_entries WHERE cache_key = ?",
                    (cache_key,),
                )
                return None
        try:
            return json.loads(value_json)
        except json.JSONDecodeError:
            return None

    def set_json(self, cache_key: str, value: Any, *, ttl_s: int | None = None) -> None:
        now = self._clock()
        ttl = self.default_ttl_s if ttl_s is None else ttl_s
        value_json = json.dumps(value, ensure_ascii=False, default=str)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cache_entries (cache_key, value_json, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (cache_key, value_json, now, now + ttl),
            )

    def delete(self, cache_key: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))

    def clear_expired(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM cache_entries WHERE expires_at <= ?",
                (self._clock(),),
            )
            return cursor.rowcount
