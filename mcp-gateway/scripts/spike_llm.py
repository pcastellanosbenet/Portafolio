"""Phase 0 spike: verify that the chosen model can select MCP tools reliably."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"
RESULTS = ROOT / "artifacts" / "spike" / "llm_tool_calling.json"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add",
            "description": "Add two integers and return the sum.",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "slow_task",
            "description": "Run a slow operation that reports progress while it waits.",
            "parameters": {
                "type": "object",
                "properties": {"seconds": {"type": "number"}},
                "required": ["seconds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "approve_action",
            "description": "Perform a destructive action after explicit user approval.",
            "parameters": {
                "type": "object",
                "properties": {"action": {"type": "string"}},
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "refresh_tools",
            "description": "Refresh the list of available tools and notify subscribers.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_probe",
            "description": "Sleep for a number of seconds so cancellation can be tested.",
            "parameters": {
                "type": "object",
                "properties": {"seconds": {"type": "number"}},
                "required": ["seconds"],
            },
        },
    },
]

TASKS: list[dict[str, Any]] = [
    {"prompt": "Suma 17 y 25.", "tool": "add"},
    {"prompt": "What is 4 plus 9?", "tool": "add"},
    {"prompt": "Espera 3 segundos y ve informando el progreso.", "tool": "slow_task"},
    {"prompt": "Run a task that takes 12 seconds and reports progress.", "tool": "slow_task"},
    {
        "prompt": "Reinicia el servicio de pagos, pero pídeme aprobación antes.",
        "tool": "approve_action",
    },
    {
        "prompt": "Delete the staging namespace after asking for confirmation.",
        "tool": "approve_action",
    },
    {"prompt": "Actualiza el catálogo de herramientas disponibles.", "tool": "refresh_tools"},
    {"prompt": "Refresh the tool list so subscribers see the change.", "tool": "refresh_tools"},
    {"prompt": "Haz una operación cancelable de 30 segundos.", "tool": "cancel_probe"},
    {"prompt": "Start a 45 second sleep that I can cancel.", "tool": "cancel_probe"},
]


def load_key() -> str:
    """Load GROQ_API_KEY from the environment or the local research-agents env file."""
    load_dotenv(ROOT.parent / "research-agents" / ".env")
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise SystemExit("GROQ_API_KEY is not available")
    return key


async def call_model(
    client: httpx.AsyncClient, model: str, api_key: str, prompt: str
) -> tuple[str | None, dict[str, Any], float]:
    """Ask the model to select one tool and return the parsed result."""
    started = time.perf_counter()
    response = await client.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a tool router. Select exactly one tool for the user request. "
                        "Do not answer the request yourself."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "tools": TOOLS,
            "tool_choice": "auto",
        },
        timeout=60,
    )
    latency = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    payload = response.json()
    message = payload["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    name = calls[0]["function"]["name"] if calls else None
    return name, payload.get("usage", {}), latency


async def run(model: str, limit: int) -> dict[str, Any]:
    """Run the tool-selection spike and persist the raw results."""
    api_key = load_key()
    records: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        for task in TASKS[:limit]:
            try:
                name, usage, latency = await call_model(client, model, api_key, task["prompt"])
                records.append(
                    {
                        "prompt": task["prompt"],
                        "expected": task["tool"],
                        "selected": name,
                        "correct": name == task["tool"],
                        "latency_ms": round(latency, 1),
                        "usage": usage,
                    }
                )
                status = "OK " if name == task["tool"] else "ERR"
                print(f"{status} {name or '-':<16} {task['prompt']}")
            except httpx.HTTPStatusError as exc:
                print(f"ERR HTTP {exc.response.status_code}: {exc.response.text[:200]}")
                records.append({"prompt": task["prompt"], "error": exc.response.status_code})
            except Exception as exc:  # noqa: BLE001 - the spike records any failure
                print(f"ERR {type(exc).__name__}: {exc}")
                records.append({"prompt": task["prompt"], "error": type(exc).__name__})

    scored = [record for record in records if "correct" in record]
    correct = sum(1 for record in scored if record["correct"])
    summary = {
        "model": model,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tasks": len(records),
        "scored": len(scored),
        "correct": correct,
        "accuracy": round(correct / len(scored), 3) if scored else 0.0,
        "latency_ms_mean": round(
            sum(record["latency_ms"] for record in scored) / len(scored), 1
        )
        if scored
        else 0.0,
        "tokens": {
            "prompt": sum(record["usage"].get("prompt_tokens", 0) for record in scored),
            "completion": sum(record["usage"].get("completion_tokens", 0) for record in scored),
            "total": sum(record["usage"].get("total_tokens", 0) for record in scored),
        },
        "records": records,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"\n{correct}/{len(scored)} correct · "
        f"{summary['accuracy']:.0%} · "
        f"{summary['latency_ms_mean']} ms mean · "
        f"{summary['tokens']['total']} tokens"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=len(TASKS))
    args = parser.parse_args()
    asyncio.run(run(args.model, args.limit))


if __name__ == "__main__":
    main()
