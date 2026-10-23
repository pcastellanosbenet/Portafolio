"""Run the research team from the command line."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.checkpoint import (
    open_async_checkpointer,
    resume_research_async,
    run_research_async,
)
from src.config import Settings
from src.graph import build_graph
from src.models import FinalReport, ResearchBrief
from src.services import build_services


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return str(value)


def _interrupt_payload(state: dict[str, Any]) -> dict[str, Any] | None:
    interrupts = state.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else {"value": value}


def _save_trace(
    state: dict[str, Any],
    *,
    question: str,
    thread_id: str,
    interrupted: bool,
) -> Path:
    trace_dir = Path("artifacts/traces")
    trace_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".paused" if interrupted else ""
    trace_path = trace_dir / f"{state['run_id']}{suffix}.json"
    payload = {
        "run_id": state["run_id"],
        "thread_id": thread_id,
        "question": question,
        "report": (
            state["report"].model_dump(mode="json") if state.get("report") is not None else None
        ),
        "usage": state["usage"].model_dump(mode="json"),
        "round": state.get("round", 0),
        "status": state.get("status"),
        "route": (
            state.get("route").model_dump(mode="json") if state.get("route") else None
        ),
        "hitl": state.get("hitl"),
        "interrupted": interrupted,
        "interrupt": _interrupt_payload(state),
        "errors": state.get("errors", []),
        "trace": [
            event.model_dump(mode="json") if hasattr(event, "model_dump") else event
            for event in state.get("trace", [])
        ],
    }
    trace_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return trace_path


def _print_report(report: FinalReport, state: dict[str, Any]) -> None:
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


async def _run(args: argparse.Namespace, settings: Settings) -> int:
    services = build_services(settings)
    async with open_async_checkpointer(settings.checkpoint_path) as saver:
        graph = build_graph(services, checkpointer=saver)
        if args.resume:
            decision = None
            if args.approve or args.reject:
                decision = {
                    "approved": bool(args.approve),
                    "feedback": args.feedback or "",
                }
            state = await resume_research_async(
                graph,
                thread_id=args.thread_id,
                decision=decision,
                recursion_limit=args.recursion_limit,
                max_concurrency=settings.max_workers,
            )
        else:
            run_id = args.run_id or uuid.uuid4().hex
            thread_id = args.thread_id or run_id
            state = await run_research_async(
                graph,
                ResearchBrief(question=args.question, language=args.language),
                run_id=run_id,
                thread_id=thread_id,
                recursion_limit=args.recursion_limit,
                max_concurrency=settings.max_workers,
            )

    thread_id = args.thread_id or state["run_id"]
    interrupted = _interrupt_payload(state) is not None
    question = state["brief"].question
    if not args.no_save:
        trace_path = _save_trace(
            state,
            question=question,
            thread_id=thread_id,
            interrupted=interrupted,
        )
        print(f"Trace: {trace_path}")
    print(f"Thread ID: {thread_id}")

    if interrupted:
        print("\nRun paused for human approval.")
        payload = _interrupt_payload(state)
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
        print(
            "\nResume with:\n"
            f"  .venv/bin/python -m scripts.run_research --resume "
            f"--thread-id {thread_id} --approve\n"
            "or reject with:\n"
            f"  .venv/bin/python -m scripts.run_research --resume "
            f"--thread-id {thread_id} --reject --feedback \"motivo\""
        )
        return 0

    report = state.get("report")
    if report is None:
        print("\nThe run finished without a report.")
        print(json.dumps(state.get("errors", []), ensure_ascii=False, indent=2))
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "report": report.model_dump(mode="json"),
                    "usage": state["usage"].model_dump(mode="json"),
                    "status": state.get("status"),
                    "hitl": state.get("hitl"),
                    "errors": state.get("errors", []),
                },
                ensure_ascii=False,
                indent=2,
                default=_json_default,
            )
        )
        return 0

    _print_report(report, state)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the multi-agent research team.")
    parser.add_argument("question", nargs="?", help="Research question.")
    parser.add_argument("--json", action="store_true", help="Print the final report as JSON.")
    parser.add_argument("--run-id", default=None, help="Optional run identifier.")
    parser.add_argument("--thread-id", default=None, help="Checkpoint thread identifier.")
    parser.add_argument("--no-save", action="store_true", help="Do not write the trace artifact.")
    parser.add_argument("--recursion-limit", type=int, default=50)
    parser.add_argument("--language", default="es")
    parser.add_argument(
        "--hitl",
        action="store_true",
        help="Pause before the writer and wait for a human decision.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume a failed run on the same thread. Use --approve/--reject "
            "when the run is paused for HITL."
        ),
    )
    decision = parser.add_mutually_exclusive_group()
    decision.add_argument("--approve", action="store_true", help="Approve the HITL draft.")
    decision.add_argument("--reject", action="store_true", help="Reject the HITL draft.")
    parser.add_argument("--feedback", default="", help="Feedback for a rejected draft.")
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Disable the fallback provider; useful when its free-tier quota is exhausted.",
    )
    args = parser.parse_args()

    if args.resume:
        if not args.thread_id:
            parser.error("--resume requires --thread-id")
        if args.feedback and not (args.approve or args.reject):
            parser.error("--feedback requires --approve or --reject")
    else:
        if not args.question:
            parser.error("question is required unless --resume is used")
        if args.approve or args.reject or args.feedback:
            parser.error("--approve/--reject/--feedback require --resume")
        if args.thread_id and args.run_id and args.thread_id != args.run_id:
            parser.error("--thread-id and --run-id must match when both are provided")

    env_file = Path(__file__).resolve().parents[1] / ".env"
    settings = Settings(_env_file=env_file)
    if args.hitl:
        settings = settings.model_copy(update={"hitl": True})
    if args.no_fallback:
        settings = settings.model_copy(update={"llm_fallback_provider": None})

    try:
        return asyncio.run(_run(args, settings))
    except KeyboardInterrupt:
        print("Interrupted. The checkpoint can be resumed with the same --thread-id.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
