"""Run five deterministic end-to-end tasks against a running gateway."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp import Client

QUERY_META_KEY = "io.mcp-gateway/query"

Task = tuple[str, str, str, dict[str, Any], Callable[[dict[str, Any]], bool]]

TASKS: list[Task] = [
    (
        "docs-mrtr",
        "¿Qué documentación hay sobre MRTR?",
        "docs__search_docs",
        {"query": "MRTR aprobación", "limit": 2},
        lambda output: any(
            result["doc_id"] == "protocolo" for result in output["results"]
        ),
    ),
    (
        "docs-security",
        "Lee la guía de seguridad y SSRF.",
        "docs__read_doc",
        {"doc_id": "seguridad"},
        lambda output: "SSRF" in output["content"] and len(output["sha256"]) == 64,
    ),
    (
        "ops-open-incidents",
        "Lista los incidentes abiertos.",
        "ops__list_incidents",
        {"status": "open"},
        lambda output: output["count"] >= 1
        and all(incident["status"] == "open" for incident in output["incidents"]),
    ),
    (
        "ops-api-metrics",
        "Mira las métricas de api de los últimos 5 minutos.",
        "ops__query_metrics",
        {"service": "api", "window_minutes": 5},
        lambda output: len(output["points"]) == 5
        and all("latency_p95_ms" in point for point in output["points"]),
    ),
    (
        "research-ssrf",
        "Busca en Wikipedia información sobre SSRF.",
        "research__wikipedia_search",
        {"query": "SSRF seguridad", "limit": 2},
        lambda output: output["mode"] == "fixtures"
        and output["results"][0]["id"] == "ssrf",
    ),
]


async def run(url: str, output_path: Path) -> int:
    records: list[dict[str, Any]] = []
    failures = 0
    async with Client(url) as client:
        for task_id, query, tool, arguments, predicate in TASKS:
            await client.list_tools(meta={QUERY_META_KEY: query})
            result = await client.call_tool(tool, arguments)
            output = result.structured_content or {}
            passed = not result.is_error and predicate(output)
            failures += 0 if passed else 1
            record = {
                "task": task_id,
                "tool": tool,
                "arguments": arguments,
                "ok": passed,
                "is_error": result.is_error,
                "trace_id": (result.meta or {}).get("trace_id"),
                "output": output,
            }
            records.append(record)
            print(f"{'OK  ' if passed else 'FAIL'}  {task_id:<20} {tool}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": url,
        "protocol_version": "2026-07-28",
        "tasks": records,
        "passed": len(records) - failures,
        "failed": failures,
    }
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\n{len(records) - failures}/{len(records)} tasks passed")
    print(f"trace written to {output_path}")
    return 0 if failures == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8765/mcp",
        help="Gateway Streamable HTTP endpoint.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/examples/smoke.json"),
        help="Where to write the sanitized JSON trace.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.url, args.output)))


if __name__ == "__main__":
    main()
