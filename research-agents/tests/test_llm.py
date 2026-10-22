"""Tests for the provider adapter without network calls."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from src.config import Settings
from src.llm import LLMClient


class Answer(BaseModel):
    text: str


class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class FakeChatModel:
    """Minimal stand-in for ChatOpenAI's structured-output API."""

    def __init__(self, behavior: str) -> None:
        self.behavior = behavior

    def with_structured_output(
        self,
        schema: type[BaseModel],
        *,
        method: str,
        include_raw: bool,
    ) -> RunnableLambda[Any, Any]:
        def invoke(_: Any) -> dict[str, Any]:
            if self.behavior == "fail":
                raise ProviderError("upstream unavailable", status_code=503)
            return {
                "parsed": schema(text="fallback answer"),
                "raw": AIMessage(
                    content="",
                    usage_metadata={
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "total_tokens": 15,
                    },
                ),
                "parsing_error": None,
            }

        assert method
        assert include_raw is True
        return RunnableLambda(invoke)


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "llm_provider": "groq",
        "llm_model": "test-main-model",
        "llm_fast_model": "test-fast-model",
        "llm_fallback_provider": "gemini",
        "llm_fallback_model": "test-fallback-model",
        "groq_api_key": "gsk-test",
        "gemini_api_key": "gemini-test",
        "llm_max_retries": 0,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_fallback_is_disabled_when_its_key_is_missing() -> None:
    settings = make_settings(gemini_api_key="")
    client = LLMClient(settings)
    assert client.fallback is None


def test_primary_target_uses_selected_provider_and_key() -> None:
    client = LLMClient(make_settings())
    assert client.primary.provider == "groq"
    assert client.primary.model == "test-main-model"
    assert client.fallback is not None
    assert client.fallback.provider == "gemini"


def test_fallback_is_used_after_retryable_primary_failure(monkeypatch: Any) -> None:
    client = LLMClient(make_settings())

    def fake_chat_model(target: Any) -> FakeChatModel:
        return FakeChatModel("fail" if target.provider == "groq" else "ok")

    monkeypatch.setattr(client, "_chat_model", fake_chat_model)
    answer, metadata = client.invoke_structured(Answer, [HumanMessage(content="hello")])

    assert answer.text == "fallback answer"
    assert metadata.provider == "gemini"
    assert metadata.usage["total_tokens"] == 15
