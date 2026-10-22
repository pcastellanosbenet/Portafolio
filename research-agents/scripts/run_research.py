"""Run the research team from the command line."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import BaseModel

from src.config import Settings
from src.graph import build_graph, run_research
from src.models import ResearchBrief
from src.services import build_services


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the multi-agent research team.")
    parser.add_argument("question", help="Research question.")
    parser.add_argument("--json", action="store_true", help="Print the final report as JSON.")
    parser.add_argument("--run-id", default=None, help="Optional run identifier.")
    parser.add_argument("--no-save", action="store_true", help="Do not write the trace artifact.")
    parser.add_argument("--recursion-limit", type=int, default=50)
    parser.add_argument("--language", default="es")
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Disable the fallback provider; useful when its free-tier quota is exhausted.",
    )
    args = parser.parse_args()

    env_file = Path(__file__).resolve().parents[1] / ".env"
    settings = Settings(_env_file=env_file)
    if args.no_fallback:
        settings = settings.model_copy(update={"llm_fallback_provider": None})
    services = build_services(settings)
    graph = build_graph(services)
    state = run_research(
        graph,
        ResearchBrief(question=args.question, language=args.language),
        run_id=args.run_id,
        recursion_limit=args.recursion_limit,
        max_concurrency=settings.max_workers,
    )
    report = state.get("report")
    if report is None:
        print("The run finished without a report.")
        print(json.dumps(state.get("errors", []), ensure_ascii=False, indent=2))
        return 1

    if not args.no_save:
        trace_dir = Path("artifacts/traces")
        trace_dir.mkdir(parents=True, exist_ok=True)
        trace_path = trace_dir / f"{state['run_id']}.json"
        trace_path.write_text(
            json.dumps(
                {
                    "run_id": state["run_id"],
                    "question": args.question,
                    "report": report.model_dump(mode="json"),
                    "usage": state["usage"].model_dump(mode="json"),
                    "round": state.get("round", 0),
                    "route": state.get("route").model_dump(mode="json")
                    if state.get("route")
                    else None,
                    "errors": state.get("errors", []),
                    "trace": [event.model_dump(mode="json") for event in state.get("trace", [])],
                },
                ensure_ascii=False,
                indent=2,
                default=_json_default,
            ),
            encoding="utf-8",
        )
        print(f"Trace: {trace_path}")

    if args.json:
        print(
            json.dumps(
                {
                    "report": report.model_dump(mode="json"),
                    "usage": state["usage"].model_dump(mode="json"),
                    "errors": state.get("errors", []),
                },
                ensure_ascii=False,
                indent=2,
                default=_json_default,
            )
        )
        return 0

    print(f"\n# {report.title}\n")
    print(report.answer_markdown)
    print("\n## Sources\n")
    for source in report.sources:
        print(f"- [{source.source_id}] {source.title} — {source.url}")
    if report.limitations:
        print("\n## Limitations\n")
        for limitation in report.limitations:
            print(f"- {limitation}")
    print(
        "\n"
        f"Usage: {state['usage'].llm_calls} LLM calls, "
        f"{state['usage'].total_tokens} tokens, "
        f"{state['usage'].search_calls} search calls."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
