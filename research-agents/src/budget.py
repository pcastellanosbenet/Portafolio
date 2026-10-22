"""Budget checks and usage accounting."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from src.config import Settings
from src.llm import InvocationMetadata
from src.models import Usage
from src.state import ResearchState


class BudgetExceeded(RuntimeError):
    """Raised when a run cannot make another model or search call."""


def usage_from_metadata(metadata: InvocationMetadata, *, latency_s: float = 0.0) -> Usage:
    """Convert provider metadata into an incremental ``Usage`` record."""
    input_tokens = metadata.usage.get("input_tokens", 0)
    output_tokens = metadata.usage.get("output_tokens", 0)
    total_tokens = metadata.usage.get("total_tokens", input_tokens + output_tokens)
    return Usage(
        llm_calls=1,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        latency_s=round(latency_s, 3),
        models={metadata.model: 1},
    )


def usage_from_ai_message(message: AIMessage, *, latency_s: float = 0.0) -> Usage:
    """Record one raw chat-model call, including tool-selection calls."""
    metadata = message.response_metadata or {}
    model = str(metadata.get("model_name") or metadata.get("model") or "tool-model")
    provider = str(metadata.get("provider") or "unknown")
    usage = message.usage_metadata or {}
    return usage_from_metadata(
        InvocationMetadata(
            provider=provider,
            model=model,
            method="tool_calling",
            usage={key: int(value) for key, value in usage.items() if isinstance(value, int)},
        ),
        latency_s=latency_s,
    )


class BudgetGuard:
    """Enforce hard limits before a node spends tokens."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def check_llm_usage(self, usage: Usage) -> None:
        if usage.llm_calls >= self.settings.max_llm_calls:
            raise BudgetExceeded(
                f"LLM call budget exhausted ({usage.llm_calls}/{self.settings.max_llm_calls})."
            )
        if usage.total_tokens >= self.settings.max_tokens:
            raise BudgetExceeded(
                f"Token budget exhausted ({usage.total_tokens}/{self.settings.max_tokens})."
            )

    def check_llm(self, state: ResearchState) -> None:
        self.check_llm_usage(state.get("usage", Usage()))

    def can_llm(self, state: ResearchState) -> bool:
        try:
            self.check_llm(state)
        except BudgetExceeded:
            return False
        return True

    def can_research(self, state: ResearchState) -> bool:
        rounds = state.get("round", 0)
        return rounds < self.settings.max_rounds and self.can_llm(state)
