"""Chat-model clients used by the evaluation runner."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
from mcp.types import Tool

DEFAULT_MODEL = "openai/gpt-oss-120b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


@dataclass(frozen=True)
class Usage:
    """Provider-reported token usage."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class ToolCall:
    """One tool call proposed by a model."""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""


@dataclass(frozen=True)
class ModelResponse:
    """A chat completion with optional tool calls."""

    content: str | None
    tool_calls: list[ToolCall]
    usage: Usage
    raw: dict[str, Any] = field(default_factory=dict)
    cache_hit: bool = False


class ModelError(RuntimeError):
    """A model request failed; callers can stop a batch and resume later."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class ChatModel(Protocol):
    """Minimal model surface needed by the evaluation runner."""

    name: str

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[Tool]
    ) -> ModelResponse:
        """Return one assistant response."""


def tool_to_openai(tool: Tool) -> dict[str, Any]:
    """Convert an MCP tool definition to the OpenAI function-tool shape."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.input_schema,
        },
    }


class GroqModel:
    """Small wrapper around Groq's OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.0,
        max_tokens: int = 512,
        max_retries: int = 4,
    ) -> None:
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        if not self.api_key:
            raise ModelError("GROQ_API_KEY is not set")
        self.name = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[Tool]
    ) -> ModelResponse:
        payload = {
            "model": self.name,
            "messages": messages,
            "temperature": self.temperature,
            "max_completion_tokens": self.max_tokens,
            "tool_choice": "auto",
            "tools": [tool_to_openai(tool) for tool in tools],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=90) as client:
            for attempt in range(self.max_retries + 1):
                response = await client.post(GROQ_URL, headers=headers, json=payload)
                if response.status_code != 429 or attempt == self.max_retries:
                    break
                retry_after = response.headers.get("retry-after")
                try:
                    delay = float(retry_after) if retry_after else 5.0
                except ValueError:
                    delay = 5.0
                await asyncio.sleep(max(1.0, delay) + attempt)
        if response.status_code == 429:
            raise ModelError(
                "Groq rate limit reached",
                status_code=429,
                retry_after=response.headers.get("retry-after"),
            )
        if response.status_code >= 400:
            message = response.text[:500]
            raise ModelError(
                f"Groq returned {response.status_code}: {message}",
                status_code=response.status_code,
            )
        data = response.json()
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise ModelError(f"unexpected Groq response: {data}") from exc

        calls: list[ToolCall] = []
        for item in message.get("tool_calls") or []:
            raw = item.get("function", {}).get("arguments", "{}")
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                arguments = {}
            calls.append(
                ToolCall(
                    id=item.get("id", ""),
                    name=item.get("function", {}).get("name", ""),
                    arguments=arguments if isinstance(arguments, dict) else {},
                    raw_arguments=raw if isinstance(raw, str) else json.dumps(raw),
                )
            )
        usage = data.get("usage") or {}
        return ModelResponse(
            content=message.get("content"),
            tool_calls=calls,
            usage=Usage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                total_tokens=int(usage.get("total_tokens", 0)),
            ),
            raw=data,
        )


class OracleModel:
    """Deterministic model used only to test the evaluation pipeline."""

    name = "fake-oracle"

    def __init__(
        self,
        task_getter: Callable[[], dict[str, Any] | None],
        mode: str,
    ) -> None:
        self.task_getter = task_getter
        self.mode = mode
        self.searched_task: str | None = None

    async def complete(
        self, _messages: list[dict[str, Any]], tools: list[Tool]
    ) -> ModelResponse:
        task = self.task_getter()
        if task is None or not task.get("gold"):
            return ModelResponse("NO_TOOL", [], Usage())
        gold = task["gold"]
        exposed = {tool.name for tool in tools}
        name = f"{gold['server']}__{gold['tool']}"
        if self.mode == "meta":
            if "invoke_tool" not in exposed:
                return ModelResponse("NO_TOOL", [], Usage())
            return ModelResponse(
                None,
                [
                    ToolCall(
                        id=f"fake-{task['id']}",
                        name="invoke_tool",
                        arguments={
                            "server": gold["server"],
                            "tool": gold["tool"],
                            "arguments": gold.get("arguments", {}),
                        },
                    )
                ],
                Usage(),
            )
        if name not in exposed:
            if "find_tools" in exposed and self.searched_task != task["id"]:
                self.searched_task = task["id"]
                return ModelResponse(
                    None,
                    [
                        ToolCall(
                            id=f"find-{task['id']}",
                            name="find_tools",
                            arguments={"query": task["query"]},
                        )
                    ],
                    Usage(),
                )
            if "invoke_tool" not in exposed:
                return ModelResponse("NO_TOOL", [], Usage())
            return ModelResponse(
                None,
                [
                    ToolCall(
                        id=f"fake-{task['id']}",
                        name="invoke_tool",
                        arguments={
                            "server": gold["server"],
                            "tool": gold["tool"],
                            "arguments": gold.get("arguments", {}),
                        },
                    )
                ],
                Usage(),
            )
        return ModelResponse(
            None,
            [
                ToolCall(
                    id=f"fake-{task['id']}",
                    name=name,
                    arguments=gold.get("arguments", {}),
                )
            ],
            Usage(),
        )


class CachedModel:
    """Persist model responses by prompt/tool hash to make runs resumable."""

    def __init__(self, inner: ChatModel, cache_dir: Path) -> None:
        self.inner = inner
        self.name = inner.name
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, messages: list[dict[str, Any]], tools: list[Tool]) -> str:
        payload = json.dumps(
            {
                "model": self.inner.name,
                "messages": messages,
                "tools": [
                    tool.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for tool in tools
                ],
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[Tool]
    ) -> ModelResponse:
        path = self.cache_dir / f"{self._key(messages, tools)}.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return ModelResponse(
                content=payload.get("content"),
                tool_calls=[ToolCall(**call) for call in payload.get("tool_calls", [])],
                usage=Usage(**payload.get("usage", {})),
                raw=payload.get("raw", {}),
                cache_hit=True,
            )
        response = await self.inner.complete(messages, tools)
        payload = {
            "content": response.content,
            "tool_calls": [asdict(call) for call in response.tool_calls],
            "usage": asdict(response.usage),
            "raw": response.raw,
        }
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return response
