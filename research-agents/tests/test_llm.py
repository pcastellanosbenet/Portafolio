"""Tests for the provider adapter without network calls."""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from src.config import Settings
from src.llm import LLMClient, TokenRateLimiter


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
        self.calls = 0

    def with_structured_output(
        self,
        schema: type[BaseModel],
        *,
        method: str,
        include_raw: bool,
    ) -> RunnableLambda[Any, Any]:
        def invoke(_: Any) -> dict[str, Any]:
            self.calls += 1
            if self.behavior == "fail":
                raise ProviderError("upstream unavailable", status_code=503)
            if self.behavior == "429_once" and self.calls == 1:
                raise ProviderError("rate limited", status_code=429)
            if self.behavior == "timeout_once" and self.calls == 1:
                raise TimeoutError("request timed out")
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


@pytest.mark.parametrize("behavior", ["429_once", "timeout_once"])
def test_retryable_errors_recover_on_the_same_provider(
    behavior: str,
    monkeypatch: Any,
) -> None:
    settings = make_settings(
        llm_fallback_provider=None,
        llm_max_retries=1,
    )
    client = LLMClient(settings)
    model = FakeChatModel(behavior)

    def fake_chat_model(target: Any) -> FakeChatModel:
        del target
        return model

    monkeypatch.setattr(client, "_chat_model", fake_chat_model)
    monkeypatch.setattr("tenacity.nap.sleep", lambda _: None)

    answer, metadata = client.invoke_structured(Answer, [HumanMessage(content="hello")])

    assert answer.text == "fallback answer"
    assert metadata.provider == "groq"
    assert model.calls == 2


class TextFallbackModel:
    """Model that rejects synthetic tool calls but can emit raw JSON."""

    def with_structured_output(
        self,
        schema: type[BaseModel],
        *,
        method: str,
        include_raw: bool,
    ) -> RunnableLambda[Any, Any]:
        del schema, method, include_raw

        def invoke(_: Any) -> dict[str, Any]:
            raise ProviderError(
                "tool_use_failed: attempted to call tool 'Answer' which was not in request.tools",
                status_code=400,
            )

        return RunnableLambda(invoke)

    def invoke(self, messages: Any) -> AIMessage:
        del messages
        return AIMessage(
            content=json.dumps({"text": "text fallback"}),
            usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
            response_metadata={"model_name": "test-fast-model"},
        )


def test_tool_use_failure_falls_back_to_raw_json(monkeypatch: Any) -> None:
    client = LLMClient(make_settings())
    model = TextFallbackModel()

    def fake_chat_model(target: Any, max_output_tokens: int | None = None) -> TextFallbackModel:
        del target, max_output_tokens
        return model

    monkeypatch.setattr(client, "_chat_model", fake_chat_model)
    answer, metadata = client.invoke_structured(Answer, [HumanMessage(content="hello")])
    assert answer.text == "text fallback"
    assert metadata.method == "text_json"
    assert metadata.usage["total_tokens"] == 10


class ToolChatModel:
    def __init__(self, behavior: str) -> None:
        self.behavior = behavior
        self.calls = 0

    def bind_tools(self, tools: Any) -> ToolChatModel:
        assert tools
        return self

    def invoke(self, messages: Any) -> AIMessage:
        del messages
        self.calls += 1
        if self.behavior == "fail":
            raise ProviderError("rate limited", status_code=429)
        return AIMessage(content="tool answer")


def test_tool_calls_do_not_use_fallback_by_default(monkeypatch: Any) -> None:
    client = LLMClient(make_settings(llm_tool_fallback=False))
    models: dict[str, ToolChatModel] = {}

    def fake_chat_model(target: Any, max_output_tokens: int | None = None) -> ToolChatModel:
        del max_output_tokens
        model = ToolChatModel("fail" if target.provider == "groq" else "ok")
        models[target.provider] = model
        return model

    monkeypatch.setattr(client, "_chat_model", fake_chat_model)
    try:
        client.invoke_with_tools([HumanMessage(content="hello")], [object()])
    except RuntimeError:
        pass
    else:
        raise AssertionError("primary tool failure should not silently succeed")
    assert models["groq"].calls == 1
    assert "gemini" not in models


def test_tool_calls_can_use_fallback_when_enabled(monkeypatch: Any) -> None:
    client = LLMClient(make_settings(llm_tool_fallback=True))
    models: dict[str, ToolChatModel] = {}

    def fake_chat_model(target: Any, max_output_tokens: int | None = None) -> ToolChatModel:
        del max_output_tokens
        model = ToolChatModel("fail" if target.provider == "groq" else "ok")
        models[target.provider] = model
        return model

    monkeypatch.setattr(client, "_chat_model", fake_chat_model)
    answer = client.invoke_with_tools([HumanMessage(content="hello")], [object()])
    assert answer.content == "tool answer"
    assert models["gemini"].calls == 1


def test_token_rate_limiter_waits_for_window() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = TokenRateLimiter(limit=10, window_s=10, clock=clock, sleep=sleep)
    limiter.acquire(8)
    limiter.acquire(4)
    assert sleeps == [10.0]
