"""Measure provider latency, structured-output reliability and token usage."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from src.config import Settings
from src.llm import LLMClient


class SpikeAnswer(BaseModel):
    """Small schema used to verify structured output on each provider."""

    summary: str = Field(description="A concise answer to the task.")
    key_points: list[str] = Field(default_factory=list, description="Two or three key points.")
    confidence: Literal["low", "medium", "high"] = Field(
        description="Confidence in the answer given the prompt."
    )


@dataclass
class SpikeResult:
    task: str
    ok: bool
    latency_s: float
    provider: str | None = None
    model: str | None = None
    method: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    error: str | None = None


TASKS: tuple[tuple[str, str], ...] = (
    (
        "summary",
        "Explain in two sentences why a multi-agent research system needs a budget guard.",
    ),
    (
        "comparison",
        "Compare a single ReAct agent with a supervisor plus specialist workers. "
        "Mention one advantage and one cost of each approach.",
    ),
    (
        "extraction",
        "Read this claim and extract the main assertion: 'The paper reports 82% accuracy "
        "on a held-out set of 500 examples, but the evaluation uses only one seed.'",
    ),
    (
        "planning",
        "Propose three subquestions to investigate whether retrieval-augmented generation "
        "reduces unsupported claims in technical reports.",
    ),
    (
        "critique",
        "Critique this statement: 'Agent frameworks always improve answer quality.' "
        "Identify the unsupported assumption.",
    ),
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("groq", "gemini"), default=None)
    parser.add_argument("--model", default=None, help="Override LLM_MODEL for this run.")
    parser.add_argument("--fast-model", default=None, help="Override LLM_FAST_MODEL.")
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Test only the selected provider, without the configured fallback.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds to wait between tasks to respect free-tier rate limits.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate settings and print the resolved targets without calling the API.",
    )
    return parser.parse_args()


def _build_settings(args: argparse.Namespace) -> Settings:
    overrides: dict[str, object] = {}
    if args.provider:
        overrides["llm_provider"] = args.provider
    if args.model:
        overrides["llm_model"] = args.model
    if args.fast_model:
        overrides["llm_fast_model"] = args.fast_model
    if args.no_fallback:
        overrides["llm_fallback_provider"] = None
        overrides["llm_fallback_model"] = ""
    return Settings(**overrides)


def _run_task(client: LLMClient, name: str, prompt: str) -> SpikeResult:
    started = time.perf_counter()
    try:
        answer, metadata = client.invoke_structured(
            SpikeAnswer,
            [HumanMessage(content=prompt)],
        )
        elapsed = time.perf_counter() - started
        usage = metadata.usage
        return SpikeResult(
            task=name,
            ok=bool(answer.summary),
            latency_s=round(elapsed, 3),
            provider=metadata.provider,
            model=metadata.model,
            method=metadata.method,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )
    except Exception as exc:  # noqa: BLE001 - the spike must report provider failures
        return SpikeResult(
            task=name,
            ok=False,
            latency_s=round(time.perf_counter() - started, 3),
            error=f"{type(exc).__name__}: {exc}",
        )


def main() -> int:
    args = _parse_args()
    settings = _build_settings(args)
    settings.ensure_runtime_dirs()

    if args.dry_run:
        print(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "primary": {
                        "provider": settings.llm_provider,
                        "model": settings.llm_model,
                        "base_url": settings.base_url_for(settings.llm_provider),
                        "api_key": "<redacted>",
                    },
                    "fallback": (
                        {
                            "provider": settings.llm_fallback_provider,
                            "model": settings.llm_fallback_model,
                            "base_url": settings.base_url_for(settings.llm_fallback_provider),
                            "api_key": "<redacted>",
                        }
                        if settings.llm_fallback_provider
                        else None
                    ),
                    "fast_model": settings.fast_model,
                    "structured_method": settings.llm_structured_method,
                },
                indent=2,
            )
        )
        return 0

    client = LLMClient(settings)
    results = []
    for index, (name, prompt) in enumerate(TASKS):
        if index and args.delay > 0:
            time.sleep(args.delay)
        results.append(_run_task(client, name, prompt))
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "primary_provider": client.primary.provider,
        "primary_model": client.primary.model,
        "fallback_provider": client.fallback.provider if client.fallback else None,
        "fallback_model": client.fallback.model if client.fallback else None,
        "results": [asdict(result) for result in results],
        "summary": {
            "tasks": len(results),
            "ok": sum(1 for result in results if result.ok),
            "total_tokens": sum(result.total_tokens for result in results),
            "mean_latency_s": round(
                sum(result.latency_s for result in results) / max(len(results), 1), 3
            ),
            "median_latency_s": round(
                statistics.median(result.latency_s for result in results), 3
            ),
        },
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Provider: {payload['primary_provider']} / {payload['primary_model']}")
        if payload["fallback_provider"]:
            print(
                f"Fallback: {payload['fallback_provider']} / {payload['fallback_model']}"
            )
        print()
        print(f"{'task':<12} {'ok':<4} {'latency':>9} {'tokens':>8}  error")
        for result in results:
            print(
                f"{result.task:<12} {str(result.ok):<4} {result.latency_s:>8.2f}s "
                f"{result.total_tokens:>8}  {result.error or ''}"
            )
        print()
        print(
            f"Completed {payload['summary']['ok']}/{payload['summary']['tasks']} tasks; "
            f"mean latency {payload['summary']['mean_latency_s']:.2f}s."
        )
    return 0 if payload["summary"]["ok"] == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
