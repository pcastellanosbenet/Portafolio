"""Persistent monthly counter for Tavily API calls."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from src.tools.base import SearchBudgetExceeded


class TavilyBudget:
    """Reserve Tavily calls atomically before hitting the network.

    The free tier allows 1,000 API calls per month. Cache hits never call this
    class, so repeated questions do not consume quota.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        monthly_limit: int = 1000,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.db_path = db_path
        self.monthly_limit = monthly_limit
        self._clock = clock
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            if str(self.db_path) != ":memory:":
                connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS api_usage (
                    provider TEXT NOT NULL,
                    period TEXT NOT NULL,
                    calls INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (provider, period)
                )
                """
            )

    def period(self) -> str:
        return self._clock().astimezone(UTC).strftime("%Y-%m")

    def used(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT calls FROM api_usage WHERE provider = 'tavily' AND period = ?",
                (self.period(),),
            ).fetchone()
        return int(row[0]) if row else 0

    def remaining(self) -> int:
        return max(self.monthly_limit - self.used(), 0)

    def reserve(self) -> int:
        """Reserve one call and return the new monthly total."""
        period = self.period()
        now = self._clock().astimezone(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT calls FROM api_usage WHERE provider = 'tavily' AND period = ?",
                (period,),
            ).fetchone()
            calls = int(row[0]) if row else 0
            if calls >= self.monthly_limit:
                raise SearchBudgetExceeded(
                    "Tavily monthly budget exhausted "
                    f"({calls}/{self.monthly_limit}) for {period}. "
                    "Cache hits still work; wait for the next month or raise the budget."
                )
            calls += 1
            connection.execute(
                """
                INSERT INTO api_usage (provider, period, calls, updated_at)
                VALUES ('tavily', ?, ?, ?)
                ON CONFLICT(provider, period) DO UPDATE SET
                    calls = excluded.calls,
                    updated_at = excluded.updated_at
                """,
                (period, calls, now),
            )
        return calls
