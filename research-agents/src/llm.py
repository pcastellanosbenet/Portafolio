"""Provider-agnostic LLM client with retries, fallback and structured output."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from src.config import Provider, Settings, StructuredMethod

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
_STRUCTURED_METHODS: tuple[StructuredMethod, ...] = (
    "json_schema",
    "function_calling",
    "json_mode",
)


class StructuredOutputError(RuntimeError):
    """Raised when a model cannot produce the requested structured output."""


@dataclass(frozen=True)
class ModelTarget:
    """A concrete provider/model pair with its credentials."""

    provider: Provider
    model: str
    api_key: SecretStr
    base_url: str


@dataclass(frozen=True)
class InvocationMetadata:
    """Metadata recorded for every structured invocation."""

    provider: str
    model: str
    method: str
    usage: dict[str, int]


def _status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if status is not None:
        try:
            return int(status)
        except (TypeError, ValueError):
            return None
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is None:
        return None
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def _is_retryable(exc: BaseException) -> bool:
    status = _status_code(exc)
    if status in _RETRYABLE_STATUS:
        return True
    name = type(exc).__name__.lower()
    return any(
        token in name
        for token in ("ratelimit", "timeout", "connection", "apiconnection", "internalserver")
    )


def _is_tool_call_error(exc: BaseException) -> bool:
    """Detect provider-specific failures when a model invents a tool call."""
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "tool_use_failed",
            "tool call validation",
            "not in request.tools",
            "failed to parse tool call",
            "failed_generation",
        )
    )


def _is_structured_method_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return _is_tool_call_error(exc) or any(
        token in message
        for token in (
            "json_schema",
            "response_format",
            "structured output",
            "function calling",
            "tool_choice",
            "parsing error",
        )
    ) or isinstance(exc, StructuredOutputError)


def parse_json_text[T: BaseModel](text: str, schema: type[T]) -> T:
    """Parse a JSON object emitted as text, tolerating fences and wrappers."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
    start = cleaned.find("{")
    if start == -1:
        raise StructuredOutputError("The model did not return a JSON object.")
    data, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    if not isinstance(data, dict):
        raise StructuredOutputError("The model returned JSON that is not an object.")
    if "arguments" in data and isinstance(data["arguments"], (dict, str)):
        arguments = data["arguments"]
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if isinstance(arguments, dict):
            data = arguments
    return schema.model_validate(data)


def _usage_from_message(message: AIMessage) -> dict[str, int]:
    usage = message.usage_metadata or {}
    return {
        key: int(value)
        for key, value in usage.items()
        if isinstance(value, int)
    }


def _estimate_text(value: str) -> int:
    """Conservative token estimate for mixed prose and JSON."""
    return max(1, len(value) // 3)


def _estimate_messages(messages: Sequence[BaseMessage]) -> int:
    return sum(_estimate_text(str(message.content)) + 4 for message in messages)


def _estimate_tools(tools: Sequence[Any]) -> int:
    payload = [
        {
            "name": getattr(tool, "name", type(tool).__name__),
            "description": getattr(tool, "description", ""),
            "args": getattr(tool, "args", {}),
        }
        for tool in tools
    ]
    return _estimate_text(json.dumps(payload, ensure_ascii=False, default=str))


def _estimate_schema(schema: type[BaseModel] | None) -> int:
    if schema is None:
        return 0
    return _estimate_text(json.dumps(schema.model_json_schema(), default=str))


class TokenRateLimiter:
    """Thread-safe sliding-window limiter for provider token quotas.

    Free tiers often cap tokens per minute. Parallel researchers share this
    limiter, so a burst of ``Send`` workers cannot exceed the configured quota.
    """

    def __init__(
        self,
        *,
        limit: int,
        window_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._sleep = sleep
        self._records: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

    def acquire(self, tokens: int) -> None:
        if self.limit <= 0:
            return
        requested = max(1, min(tokens, self.limit))
        while True:
            with self._lock:
                now = self._clock()
                while self._records and now - self._records[0][0] >= self.window_s:
                    self._records.popleft()
                used = sum(amount for _, amount in self._records)
                if used + requested <= self.limit:
                    self._records.append((now, requested))
                    return
                if self._records:
                    wait = self.window_s - (now - self._records[0][0])
                else:
                    wait = self.window_s
            self._sleep(max(0.1, wait))


class LLMClient:
    """Small adapter around ``ChatOpenAI`` for Groq and Gemini.

    Both providers expose OpenAI-compatible endpoints, so a single client
    implementation can switch providers through settings. Retries and fallback
    are handled here rather than in agent nodes, keeping the graph simple.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._primary = ModelTarget(
            provider=settings.llm_provider,
            model=settings.llm_model,
            api_key=settings.primary_api_key,
            base_url=settings.base_url_for(settings.llm_provider),
        )
        self._fallback: ModelTarget | None = None
        if settings.llm_fallback_provider:
            if settings.has_api_key_for(settings.llm_fallback_provider):
                self._fallback = ModelTarget(
                    provider=settings.llm_fallback_provider,
                    model=settings.llm_fallback_model,
                    api_key=settings.fallback_api_key,  # type: ignore[arg-type]
                    base_url=settings.base_url_for(settings.llm_fallback_provider),
                )
            else:
                logger.warning(
                    "Fallback provider %s is configured but its API key is missing; "
                    "fallback disabled for this run.",
                    settings.llm_fallback_provider,
                )
        self._limiter = TokenRateLimiter(
            limit=settings.llm_tpm_limit,
            window_s=settings.llm_tpm_window_s,
        )

    @property
    def primary(self) -> ModelTarget:
        return self._primary

    @property
    def fallback(self) -> ModelTarget | None:
        return self._fallback

    def _targets(self, *, fast: bool) -> list[ModelTarget]:
        primary_model = self.settings.fast_model if fast else self._primary.model
        targets = [
            ModelTarget(
                provider=self._primary.provider,
                model=primary_model,
                api_key=self._primary.api_key,
                base_url=self._primary.base_url,
            )
        ]
        if self._fallback is not None:
            targets.append(self._fallback)
        return targets

    def _chat_model(
        self,
        target: ModelTarget,
        *,
        max_output_tokens: int | None = None,
    ) -> BaseChatModel:
        return ChatOpenAI(
            model=target.model,
            api_key=target.api_key.get_secret_value(),
            base_url=target.base_url,
            temperature=self.settings.llm_temperature,
            timeout=self.settings.llm_timeout_s,
            max_retries=0,
            max_tokens=max_output_tokens or self.settings.llm_max_output_tokens,
        )

    def chat_model(self, *, fast: bool = False) -> BaseChatModel:
        """Return the primary chat model so tools can be bound to it."""
        return self._chat_model(self._targets(fast=fast)[0])

    def _acquire_for(
        self,
        messages: Sequence[BaseMessage],
        *,
        tools: Sequence[Any] = (),
        schema: type[BaseModel] | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        estimated = (
            _estimate_messages(messages)
            + _estimate_tools(tools)
            + _estimate_schema(schema)
            + (max_output_tokens or self.settings.llm_max_output_tokens)
        )
        self._limiter.acquire(estimated)

    def _retrying(self) -> Retrying:
        return Retrying(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(self.settings.llm_max_retries + 1),
            wait=wait_exponential_jitter(initial=1, max=20),
            reraise=True,
        )

    def invoke_text(
        self,
        messages: Sequence[BaseMessage],
        *,
        fast: bool = False,
    ) -> AIMessage:
        """Invoke a chat model and return the raw message."""
        last_error: BaseException | None = None
        for target in self._targets(fast=fast):
            output_tokens = min(self.settings.llm_max_output_tokens, 3_000)
            model = self._chat_model(target, max_output_tokens=output_tokens)
            try:
                for attempt in self._retrying():
                    with attempt:
                        self._acquire_for(messages, max_output_tokens=output_tokens)
                        response = model.invoke(messages)
                if not isinstance(response, AIMessage):
                    raise TypeError(f"Expected AIMessage, got {type(response)!r}")
                return response
            except Exception as exc:  # noqa: BLE001 - provider errors are normalized
                last_error = exc
                if not _is_retryable(exc):
                    raise
                logger.warning(
                    "Provider %s failed after retries; trying fallback if available: %s",
                    target.provider,
                    type(exc).__name__,
                )
        if last_error is not None:
            raise RuntimeError(
                "All configured LLM providers failed. "
                f"Last error: {type(last_error).__name__}: {last_error}"
            ) from last_error
        raise RuntimeError("No LLM provider is configured.")

    def invoke_with_tools(
        self,
        messages: Sequence[BaseMessage],
        tools: Sequence[Any],
        *,
        fast: bool = False,
    ) -> AIMessage:
        """Invoke a model with tools, retrying and falling back on provider errors."""
        last_error: BaseException | None = None
        targets = self._targets(fast=fast)
        if not self.settings.llm_tool_fallback:
            targets = targets[:1]
        for target in targets:
            output_tokens = min(self.settings.llm_max_output_tokens, 1_024)
            model = self._chat_model(target, max_output_tokens=output_tokens).bind_tools(tools)
            try:
                for attempt in self._retrying():
                    with attempt:
                        self._acquire_for(
                            messages,
                            tools=tools,
                            max_output_tokens=output_tokens,
                        )
                        response = model.invoke(messages)
                if not isinstance(response, AIMessage):
                    raise TypeError(f"Expected AIMessage, got {type(response)!r}")
                return response
            except Exception as exc:  # noqa: BLE001 - provider errors are normalized
                last_error = exc
                if not _is_retryable(exc):
                    raise
                logger.warning(
                    "Tool call failed on %s after retries; trying fallback: %s",
                    target.provider,
                    type(exc).__name__,
                )
        if last_error is not None:
            raise RuntimeError(
                "All configured LLM providers failed. "
                f"Last error: {type(last_error).__name__}: {last_error}"
            ) from last_error
        raise RuntimeError("No LLM provider is configured.")

    def _invoke_structured_text[T: BaseModel](
        self,
        schema: type[T],
        messages: Sequence[BaseMessage],
        *,
        fast: bool = False,
    ) -> tuple[T, InvocationMetadata]:
        """Last-resort structured output: ask for raw JSON and parse it locally.

        Some free-tier Groq models occasionally emit a tool call to the schema
        name instead of using the synthetic tool supplied by LangChain. A plain
        text request with an explicit JSON schema avoids that provider quirk.
        """
        schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        instruction = HumanMessage(
            content=(
                "Return ONLY one JSON object that validates against this JSON schema. "
                "Do not call tools, do not use Markdown fences, and do not add prose.\n\n"
                f"{schema_text}"
            )
        )
        response = self.invoke_text([*messages, instruction], fast=fast)
        parsed = parse_json_text(str(response.content), schema)
        model_name = str(response.response_metadata.get("model_name") or self.primary.model)
        return parsed, InvocationMetadata(
            provider=self.settings.llm_provider,
            model=model_name,
            method="text_json",
            usage=_usage_from_message(response),
        )

    def invoke_structured[T: BaseModel](
        self,
        schema: type[T],
        messages: Sequence[BaseMessage],
        *,
        fast: bool = False,
    ) -> tuple[T, InvocationMetadata]:
        """Invoke a model and parse its answer into ``schema``.

        The configured structured-output method is attempted first. If the
        provider rejects that method, the remaining methods are tried before
        moving to the fallback provider. Retryable provider errors trigger
        exponential backoff and then fallback.
        """
        methods = [self.settings.llm_structured_method]
        methods.extend(method for method in _STRUCTURED_METHODS if method not in methods)

        last_error: BaseException | None = None
        for target in self._targets(fast=fast):
            model = self._chat_model(target)
            for method in methods:
                try:
                    for attempt in self._retrying():
                        with attempt:
                            self._acquire_for(messages, schema=schema)
                            response = model.with_structured_output(
                                schema,
                                method=method,
                                include_raw=True,
                            ).invoke(messages)
                    parsed, raw, parsing_error = _unpack_structured_response(response, schema)
                    if parsing_error is not None:
                        raise StructuredOutputError(str(parsing_error))
                    return parsed, InvocationMetadata(
                        provider=target.provider,
                        model=target.model,
                        method=method,
                        usage=_usage_from_message(raw),
                    )
                except Exception as exc:  # noqa: BLE001 - provider errors are normalized
                    last_error = exc
                    if _is_retryable(exc):
                        logger.warning(
                            "Provider %s failed after retries; trying fallback if available.",
                            target.provider,
                        )
                        break
                    if _is_tool_call_error(exc):
                        logger.info(
                            "Provider %s rejected a synthetic tool call; using text JSON fallback.",
                            target.provider,
                        )
                        return self._invoke_structured_text(schema, messages, fast=fast)
                    if _is_structured_method_error(exc):
                        logger.info(
                            "Structured method %s failed for %s; trying another method.",
                            method,
                            target.provider,
                        )
                        continue
                    raise
        try:
            return self._invoke_structured_text(schema, messages, fast=fast)
        except Exception as exc:  # noqa: BLE001 - expose the text fallback error
            last_error = exc
        if last_error is not None:
            raise RuntimeError(
                "All configured LLM providers failed. "
                f"Last error: {type(last_error).__name__}: {last_error}"
            ) from last_error
        raise RuntimeError("No LLM provider is configured.")


def _unpack_structured_response[T: BaseModel](
    response: Any,
    schema: type[T],
) -> tuple[T, AIMessage, BaseException | None]:
    if isinstance(response, dict) and "parsed" in response:
        parsed = response.get("parsed")
        raw = response.get("raw")
        parsing_error = response.get("parsing_error")
        if not isinstance(raw, AIMessage):
            raise TypeError("Structured response did not include a raw AIMessage.")
        if parsing_error is not None:
            return parsed, raw, parsing_error
        if not isinstance(parsed, schema):
            raise StructuredOutputError(
                f"Expected {schema.__name__}, got {type(parsed).__name__}."
            )
        return parsed, raw, None
    if isinstance(response, schema):
        raise StructuredOutputError(
            "Provider returned a parsed object without raw metadata; "
            "structured output must be invoked with include_raw=True."
        )
    raise StructuredOutputError(
        f"Unexpected structured response type: {type(response).__name__}."
    )
