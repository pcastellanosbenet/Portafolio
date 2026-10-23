"""Tests for provider and model selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import PROVIDER_BASE_URLS, Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "llm_provider": "groq",
        "llm_model": "test-main-model",
        "llm_fast_model": "test-fast-model",
        "llm_fallback_provider": None,
        "llm_fallback_model": "",
        "groq_api_key": "gsk-test",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_provider_base_urls_are_configured() -> None:
    assert PROVIDER_BASE_URLS["groq"].startswith("https://api.groq.com/")
    assert PROVIDER_BASE_URLS["gemini"].startswith("https://generativelanguage.googleapis.com/")


def test_fast_model_falls_back_to_main_model() -> None:
    settings = make_settings(llm_fast_model="")
    assert settings.fast_model == "test-main-model"


def test_api_key_selection_uses_active_provider() -> None:
    settings = make_settings()
    assert settings.primary_api_key.get_secret_value() == "gsk-test"


def test_missing_api_key_raises_actionable_error() -> None:
    settings = make_settings(groq_api_key="")
    with pytest.raises(ValueError, match="GROQ_API_KEY is not set"):
        _ = settings.primary_api_key


def test_fallback_requires_its_own_key() -> None:
    settings = make_settings(
        llm_fallback_provider="gemini",
        llm_fallback_model="test-gemini-model",
    )
    with pytest.raises(ValueError, match="GEMINI_API_KEY is not set"):
        _ = settings.fallback_api_key


def test_empty_fallback_provider_is_disabled() -> None:
    settings = make_settings(llm_fallback_provider="")
    assert settings.llm_fallback_provider is None
    assert settings.fallback_api_key is None


def test_model_is_required() -> None:
    with pytest.raises(ValueError, match="LLM_MODEL is required"):
        make_settings(llm_model="")


def test_runtime_directory_is_created(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "research.db"
    settings = make_settings(db_path=db_path)
    settings.ensure_runtime_dirs()
    assert db_path.parent.is_dir()


def test_judge_target_defaults_to_the_fast_model() -> None:
    settings = make_settings()
    assert settings.judge_target == ("groq", "test-fast-model")


def test_judge_target_can_use_an_independent_provider() -> None:
    settings = make_settings(
        judge_provider="gemini",
        judge_model="test-gemini-judge",
        gemini_api_key="gm-test",
    )
    assert settings.judge_target == ("gemini", "test-gemini-judge")


def test_judge_provider_requires_a_judge_model() -> None:
    with pytest.raises(ValueError, match="JUDGE_MODEL is required"):
        make_settings(judge_provider="gemini", judge_model="", gemini_api_key="gm-test")


def test_judge_settings_use_research_env_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_JUDGE_PROVIDER", "gemini")
    monkeypatch.setenv("RESEARCH_JUDGE_MODEL", "test-env-judge")
    settings = make_settings(gemini_api_key="gm-test")
    assert settings.judge_target == ("gemini", "test-env-judge")
