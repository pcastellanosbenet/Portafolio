"""Tests for budget enforcement and usage conversion."""

from __future__ import annotations

import pytest

from src.budget import BudgetExceeded, BudgetGuard, usage_from_metadata
from src.config import Settings
from src.llm import InvocationMetadata
from src.models import ResearchBrief, Usage
from src.state import initial_state


def test_llm_call_budget_is_enforced() -> None:
    settings = Settings(
        _env_file=None,
        llm_model="test",
        groq_api_key="test",
        max_llm_calls=1,
    )
    guard = BudgetGuard(settings)
    with pytest.raises(BudgetExceeded, match="LLM call budget"):
        guard.check_llm_usage(Usage(llm_calls=1))


def test_token_budget_is_enforced() -> None:
    settings = Settings(
        _env_file=None,
        llm_model="test",
        groq_api_key="test",
        max_tokens=1000,
    )
    guard = BudgetGuard(settings)
    with pytest.raises(BudgetExceeded, match="Token budget"):
        guard.check_llm_usage(Usage(total_tokens=1000))


def test_can_research_respects_round_limit() -> None:
    settings = Settings(
        _env_file=None,
        llm_model="test",
        groq_api_key="test",
        max_rounds=1,
    )
    guard = BudgetGuard(settings)
    state = initial_state(ResearchBrief(question="A question?"))
    state["round"] = 1
    assert guard.can_research(state) is False


def test_usage_from_metadata_uses_total_tokens_fallback() -> None:
    metadata = InvocationMetadata(
        provider="fake",
        model="fake-model",
        method="json_schema",
        usage={"input_tokens": 7, "output_tokens": 5},
    )
    usage = usage_from_metadata(metadata, latency_s=0.5)
    assert usage.total_tokens == 12
    assert usage.llm_calls == 1
    assert usage.models == {"fake-model": 1}
    assert usage.latency_s == 0.5
