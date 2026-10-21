"""Measure Ollama latency and throughput on this machine.

This is an infrastructure benchmark, not a model-quality evaluation.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

PROMPT = (
    "Explain in about 150 words the difference between a KNX datapoint type "
    "and a KNX group address. Be precise and concise."
)


def _models(base_url: str) -> list[str]:
    try:
        response = httpx.get(f"{base_url}/api/tags", timeout=10)
        response.raise_for_status()
        return [model["name"] for model in response.json().get("models", [])]
    except httpx.HTTPError:
        return []


def _ollama_ps(base_url: str) -> list[dict]:
    """Return the models currently loaded, including their memory footprint."""
    try:
        response = httpx.get(f"{base_url}/api/ps", timeout=10)
        response.raise_for_status()
        models = response.json().get("models", [])
        return [
            {
                "name": model.get("name"),
                "size_bytes": model.get("size"),
                "size_vram_bytes": model.get("size_vram"),
            }
            for model in models
        ]
    except httpx.HTTPError as error:
        return [{"error": str(error)}]


def run_once(
    base_url: str,
    model: str,
    *,
    context: int,
    predict: int,
    threads: int,
) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_ctx": context,
            "num_predict": predict,
            "num_thread": threads,
        },
    }
    started = time.perf_counter()
    response = httpx.post(f"{base_url}/api/chat", json=payload, timeout=600)
    total_seconds = time.perf_counter() - started
    response.raise_for_status()
    data = response.json()
    prompt_count = int(data.get("prompt_eval_count", 0) or 0)
    prompt_ns = int(data.get("prompt_eval_duration", 0) or 0)
    eval_count = int(data.get("eval_count", 0) or 0)
    eval_ns = int(data.get("eval_duration", 0) or 0)
    return {
        "total_seconds": round(total_seconds, 2),
        "prompt_tokens": prompt_count,
        "output_tokens": eval_count,
        "prompt_tokens_per_second": round(
            prompt_count / (prompt_ns / 1e9), 2
        )
        if prompt_ns
        else None,
        "output_tokens_per_second": round(eval_count / (eval_ns / 1e9), 2)
        if eval_ns
        else None,
        "load_seconds": round(float(data.get("load_duration", 0) or 0) / 1e9, 2),
        "answer_preview": str(data.get("message", {}).get("content", ""))[:300],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark local Ollama.")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen2.5:1.5b-instruct-q4_K_M")
    parser.add_argument("--context", type=int, default=4096)
    parser.add_argument("--predict", type=int, default=200)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--output", type=Path, default=Path("docs/ollama_benchmark.json"))
    args = parser.parse_args()

    installed = _models(args.base_url)
    if not installed:
        raise SystemExit(
            "Ollama no responde. Instálalo y arráncalo con `ollama serve`; "
            f"después ejecuta `ollama pull {args.model}`."
        )
    if args.model not in installed:
        raise SystemExit(
            f"El modelo {args.model} no está descargado. Ejecuta `ollama pull {args.model}`."
        )

    runs = []
    for index in range(args.runs):
        result = run_once(
            args.base_url,
            args.model,
            context=args.context,
            predict=args.predict,
            threads=args.threads,
        )
        result["run"] = index + 1
        result["cold"] = result["load_seconds"] > 0
        runs.append(result)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    report = {
        "model": args.model,
        "context": args.context,
        "predict": args.predict,
        "threads": args.threads,
        "runs": runs,
        "loaded_models": _ollama_ps(args.base_url),
        "note": "Benchmark de infraestructura; no es una métrica de calidad del RAG.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Resultados guardados en {args.output}")


if __name__ == "__main__":
    main()
