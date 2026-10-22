"""Tests for the persistent Tavily monthly quota."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.tavily_budget import TavilyBudget
from src.tools.base import SearchBudgetExceeded


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def test_reserve_increments_and_enforces_limit(tmp_path: Path) -> None:
    budget = TavilyBudget(tmp_path / "usage.db", monthly_limit=2)
    assert budget.reserve() == 1
    assert budget.reserve() == 2
    assert budget.used() == 2
    assert budget.remaining() == 0
    with pytest.raises(SearchBudgetExceeded, match="monthly budget exhausted"):
        budget.reserve()


def test_counter_resets_on_a_new_month(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 10, 22, tzinfo=UTC))
    budget = TavilyBudget(tmp_path / "usage.db", monthly_limit=1, clock=clock)
    assert budget.reserve() == 1
    with pytest.raises(SearchBudgetExceeded):
        budget.reserve()
    clock.now = datetime(2026, 11, 1, tzinfo=UTC)
    assert budget.used() == 0
    assert budget.reserve() == 1
