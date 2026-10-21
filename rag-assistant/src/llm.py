"""LLM clients with a local-first Ollama implementation."""

from __future__ import annotations

from typing import Any, Protocol

import httpx


class LLMError(RuntimeError):
    """Raised when the local model cannot produce a response."""


class LLMClient(Protocol):
    def generate(self, system: str, user: str) -> str: ...


class OllamaClient:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5:1.5b-instruct-q4_K_M",
        num_ctx: int = 4096,
        num_predict: int = 300,
        num_thread: int = 2,
        timeout: int = 300,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.num_thread = num_thread
        self.timeout = timeout

    def generate(self, system: str, user: str) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.0,
                "top_p": 0.9,
                "repeat_penalty": 1.05,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
                "num_thread": self.num_thread,
            },
        }
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise LLMError(
                f"No se pudo contactar con Ollama en {self.base_url}: {error}"
            ) from error
        data = response.json()
        content = data.get("message", {}).get("content", "")
        if not content:
            raise LLMError("Ollama devolvió una respuesta vacía.")
        return str(content)

    def health(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            return response.is_success
        except httpx.HTTPError:
            return False


class MockLLM:
    """Deterministic client used by tests and by the extractive fallback."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response
