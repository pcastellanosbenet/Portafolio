"""Shared test fixtures for the research graph."""

from __future__ import annotations

import pytest

from src.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="groq",
        llm_model="test-main-model",
        llm_fast_model="test-fast-model",
        llm_fallback_provider=None,
        groq_api_key="gsk-test",
        max_llm_calls=20,
        max_tokens=100_000,
        max_rounds=2,
    )
