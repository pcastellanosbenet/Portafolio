"""Resumable evaluation runner for static, meta and hybrid routing."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import statistics
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
from mcp import Client
from mcp.types import ElicitRequestParams, ElicitResult, Tool

from src.config import Settings
from src.gateway.audit import AuditLog
from src.gateway.policy import PolicyEngine
from src.gateway.router import QUERY_META_KEY, count_tool_tokens
from src.gateway.runner import build_upstreams
from src.gateway.server import Gateway
from src.host.llm import (
    DEFAULT_MODEL,
    CachedModel,
    GroqModel,
    ModelError,
    ModelResponse,
    OracleModel,
    Usage,
)
from src.upstreams.local import local_upstreams

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS = ROOT / "eval" / "tasks.jsonl"
DEFAULT_RESULTS = ROOT / "eval" / "results"
DEFAULT_CACHE = ROOT / "eval" / "cache"
CONFIG_NAMES = ("static", "meta", "hybrid")


def load_tasks(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_messages(task: dict[str, Any], config: str) -> list[dict[str, Any]]:
    system = (
        "You evaluate a tool gateway. Solve the user task by choosing at most one "
        "tool. Use the most specific tool: read_doc, wikipedia_get and arxiv_get "
        "read a named document or page, while the search tools find candidates. "
        "Use a tool only if it fully solves the task; otherwise reply exactly "
        "NO_TOOL. Do not ask follow-up questions and do not invent tool names."
    )
    if config == "meta":
        system += (
            " Only find_tools and invoke_tool are exposed. Call find_tools first "
            "when needed, then invoke_tool with server, tool and arguments."
        )
    elif config == "hybrid":
        system += (
            " Prefer the listed tools. find_tools and invoke_tool are available as "
            "a fallback for tools that are not listed."
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": task["query"]},
    ]


def assistant_message(response: ModelResponse) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": response.content or "",
    }
    if response.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id or f"call-{index}",
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": call.raw_arguments
                    or json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for index, call in enumerate(response.tool_calls)
        ]
    return message


def tool_result_text(result: Any) -> str:
    if result.structured_content is not None:
        text = json.dumps(result.structured_content, ensure_ascii=False)
    else:
        text = "\n".join(
            item.text for item in result.content if item.type == "text"
        )
    return text[:4000]


def actual_selection(call: Any) -> tuple[str, dict[str, Any]] | None:
    """Unwrap invoke_tool into the underlying namespaced tool."""
    if call.name == "find_tools":
        return None
    if call.name == "invoke_tool":
        server = str(call.arguments.get("server", "")).strip().removesuffix("-mcp")
        tool = str(call.arguments.get("tool", "")).strip()
        if not server or not tool:
            return "", {}
        name = tool if "__" in tool else f"{server}__{tool}"
        nested = call.arguments.get("arguments", {})
        return name, nested if isinstance(nested, dict) else {}
    return call.name, call.arguments


def get_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def predicate_matches(predicate: dict[str, Any], output: Any, text: str) -> bool:
    kind = predicate["type"]
    if kind == "contains":
        haystack = (json.dumps(output, ensure_ascii=False) + " " + text).lower()
        return str(predicate["value"]).lower() in haystack
    if kind == "path_equals":
        return get_path(output, predicate["path"]) == predicate["value"]
    if kind == "path_min":
        value = get_path(output, predicate["path"])
        return isinstance(value, int | float) and value >= predicate["value"]
    if kind == "path_len":
        value = get_path(output, predicate["path"])
        return isinstance(value, list) and len(value) == predicate["value"]
    if kind == "all":
        return all(
            predicate_matches(item, output, text) for item in predicate["predicates"]
        )
    raise ValueError(f"unknown predicate: {kind}")


def is_valid_arguments(
    descriptor: Any, arguments: dict[str, Any]
) -> bool:
    if descriptor is None:
        return False
    try:
        jsonschema.Draft202012Validator(descriptor.tool.input_schema).validate(
            arguments
        )
        return True
    except jsonschema.ValidationError:
        return False


def usage_sum(usages: list[Usage]) -> Usage:
    return Usage(
        prompt_tokens=sum(usage.prompt_tokens for usage in usages),
        completion_tokens=sum(usage.completion_tokens for usage in usages),
        total_tokens=sum(usage.total_tokens for usage in usages),
    )


async def execute_task(
    task: dict[str, Any],
    client: Client,
    model: Any,
    gateway: Gateway,
    config: str,
    current_task: list[dict[str, Any] | None],
) -> dict[str, Any]:
    current_task[0] = task
    started = time.perf_counter()
    route_started = time.perf_counter()
    meta = {QUERY_META_KEY: task["query"]} if config == "hybrid" else None
    tools_result = await client.list_tools(meta=meta)
    route_ms = (time.perf_counter() - route_started) * 1000
    tools: list[Tool] = tools_result.tools
    initial_tool_tokens = count_tool_tokens(tools)

    messages = build_messages(task, config)
    usages: list[Usage] = []
    calls: list[dict[str, Any]] = []
    actual_name: str | None = None
    actual_args: dict[str, Any] = {}
    output: Any = None
    result_text = ""
    tool_error: str | None = None
    final_text = ""
    found_tool_tokens = 0
    gateway_ms = 0.0
    cache_hit = False

    try:
        for _round in range(4):
            response = await model.complete(messages, tools)
            usages.append(response.usage)
            cache_hit = cache_hit or response.cache_hit
            messages.append(assistant_message(response))
            if not response.tool_calls:
                final_text = response.content or ""
                break
            stop = False
            for call in response.tool_calls:
                call_started = time.perf_counter()
                try:
                    result = await client.call_tool(call.name, call.arguments)
                except Exception as exc:  # noqa: BLE001 - a bad call is a scored failure
                    gateway_ms += (time.perf_counter() - call_started) * 1000
                    result_text = f"{type(exc).__name__}: {exc}"
                    calls.append(
                        {
                            "name": call.name,
                            "arguments": call.arguments,
                            "is_error": True,
                            "trace_id": None,
                            "error": result_text[:300],
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id or "call-error",
                            "name": call.name,
                            "content": result_text[:4000],
                        }
                    )
                    if call.name != "find_tools":
                        selected = actual_selection(call)
                        if selected is not None:
                            actual_name, actual_args = selected
                            tool_error = result_text
                            stop = True
                            break
                    continue
                gateway_ms += (time.perf_counter() - call_started) * 1000
                text = tool_result_text(result)
                calls.append(
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                        "is_error": result.is_error,
                        "trace_id": (result.meta or {}).get("trace_id"),
                        "error": text[:300] if result.is_error else None,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id or "call-result",
                        "name": call.name,
                        "content": text,
                    }
                )
                if call.name == "find_tools" and result.structured_content:
                    found_tool_tokens += int(
                        result.structured_content.get("tool_tokens", 0)
                    )
                    continue
                selected = actual_selection(call)
                if selected is not None:
                    actual_name, actual_args = selected
                    output = (
                        result.structured_content
                        if result.structured_content is not None
                        else {"text": text}
                    )
                    result_text = text
                    if result.is_error:
                        tool_error = text
                    stop = True
                    break
            if stop:
                break
    except ModelError as exc:
        return {
            "task_id": task["id"],
            "block": task["block"],
            "config": config,
            "model": model.name,
            "status": "model_error",
            "error": str(exc),
            "retry_after": exc.retry_after,
        }

    expected = (
        f"{task['gold']['server']}__{task['gold']['tool']}"
        if task["gold"] is not None
        else None
    )
    selection_ok = actual_name == expected
    descriptor = gateway.catalog.get(actual_name) if actual_name else None
    arguments_valid = (
        is_valid_arguments(descriptor, actual_args) if actual_name else True
    )
    gold_arguments_match = None
    if expected and actual_name:
        gold_args = task["gold"]["arguments"]
        gold_arguments_match = all(
            actual_args.get(key) == value for key, value in gold_args.items()
        )

    if expected is None:
        success = actual_name is None
        success = success and not tool_error
    else:
        success = (
            selection_ok
            and arguments_valid
            and output is not None
            and not tool_error
            and predicate_matches(task["success"], output, result_text)
        )

    total_ms = (time.perf_counter() - started) * 1000
    return {
        "task_id": task["id"],
        "block": task["block"],
        "config": config,
        "model": model.name,
        "status": "ok",
        "expected": expected,
        "selected": actual_name,
        "selected_args": actual_args,
        "selection_ok": selection_ok,
        "arguments_valid": arguments_valid,
        "gold_arguments_match": gold_arguments_match,
        "success": success,
        "abstained": actual_name is None,
        "unnecessary_call": expected is None and actual_name is not None,
        "calls": calls,
        "tool_tokens": initial_tool_tokens + found_tool_tokens,
        "initial_tool_tokens": initial_tool_tokens,
        "found_tool_tokens": found_tool_tokens,
        "usage": asdict(usage_sum(usages)),
        "route_ms": round(route_ms, 3),
        "gateway_ms": round(gateway_ms, 3),
        "total_ms": round(total_ms, 3),
        "cache_hit": cache_hit,
        "final_text": final_text[:500],
        "error": tool_error[:500] if tool_error else None,
    }


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 3)


def block_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    positives = [record for record in records if record.get("expected")]
    negatives = [record for record in records if record.get("expected") is None]
    return {
        "count": len(records),
        "selection_accuracy": round(
            sum(record["selection_ok"] for record in positives) / len(positives), 4
        )
        if positives
        else 0.0,
        "argument_validity": round(
            sum(record["arguments_valid"] for record in positives) / len(positives), 4
        )
        if positives
        else 0.0,
        "task_success": round(
            sum(record["success"] for record in records) / len(records), 4
        )
        if records
        else 0.0,
        "abstention_rate": round(
            sum(record["abstained"] for record in negatives) / len(negatives), 4
        )
        if negatives
        else None,
        "unnecessary_call_rate": round(
            sum(record["unnecessary_call"] for record in negatives) / len(negatives), 4
        )
        if negatives
        else None,
        "mean_tool_tokens": round(
            statistics.fmean(record["tool_tokens"] for record in records), 2
        )
        if records
        else 0.0,
        "mean_prompt_tokens": round(
            statistics.fmean(record["usage"]["prompt_tokens"] for record in records), 2
        )
        if records
        else 0.0,
        "p50_total_ms": percentile([record["total_ms"] for record in records], 0.5),
        "p95_total_ms": percentile([record["total_ms"] for record in records], 0.95),
        "cache_hit_rate": round(
            sum(record["cache_hit"] for record in records) / len(records), 4
        )
        if records
        else 0.0,
    }


def summarize(
    records: list[dict[str, Any]],
    config: str,
    model_name: str,
    tasks_hash: str,
    partial: bool,
) -> dict[str, Any]:
    by_block = {
        block: block_summary(
            [record for record in records if record["block"] == block]
        )
        for block in ("docs", "research", "ops", "negative")
    }
    failures = [
        {
            "task_id": record["task_id"],
            "expected": record.get("expected"),
            "selected": record.get("selected"),
            "selection_ok": record.get("selection_ok"),
            "arguments_valid": record.get("arguments_valid"),
            "error": record.get("error"),
        }
        for record in records
        if record.get("status") == "ok" and not record.get("success")
    ]
    return {
        "config": config,
        "model": model_name,
        "tasks_sha256": tasks_hash,
        "partial": partial,
        "count": len(records),
        "overall": block_summary(records),
        "by_block": by_block,
        "failures": failures,
        "errors": [
            record
            for record in records
            if record.get("status") == "model_error"
        ],
    }


def read_completed(path: Path) -> set[str]:
    if not path.exists():
        return set()
    completed: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("status") == "ok":
            completed.add(record["task_id"])
    return completed


async def run(args: argparse.Namespace) -> int:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.WARNING)
    tasks = load_tasks(args.tasks)
    tasks_hash = hashlib.sha256(args.tasks.read_bytes()).hexdigest()
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.force and output.exists():
        output.unlink()
    completed = read_completed(output)
    tasks_for_run = tasks
    if args.task_ids:
        wanted = {item.strip() for item in args.task_ids.split(",") if item.strip()}
        tasks_for_run = [task for task in tasks if task["id"] in wanted]
        missing = wanted - {task["id"] for task in tasks_for_run}
        if missing:
            raise ValueError(f"unknown task ids: {sorted(missing)}")
    selected = [
        task
        for task in tasks_for_run
        if task["id"] not in completed
    ][args.offset : args.offset + args.limit if args.limit else None]

    current_task: list[dict[str, Any] | None] = [None]

    async def answer_approval(
        _context: Any, _params: ElicitRequestParams
    ) -> ElicitResult:
        task = current_task[0]
        accepted = bool(task and task.get("approval") == "accept")
        return ElicitResult(
            action="accept" if accepted else "decline",
            content={"approve": True} if accepted else None,
        )

    with local_upstreams() as (docs_url, ops_url):
        settings = Settings(
            gateway_db_path=":memory:",
            gateway_router_mode=args.config,
            gateway_top_k=args.top_k,
            gateway_approval_mode="risk",
            gateway_max_retries=0,
            docs_mcp_url=docs_url,
            ops_mcp_url=ops_url,
            llm_model=args.llm_model,
        )
        gateway = Gateway(
            settings,
            build_upstreams(settings),
            audit=AuditLog(":memory:"),
            policy=PolicyEngine("risk"),
        )
        await gateway.start()
        if len(gateway.catalog) != 22:
            raise RuntimeError(
                f"expected 22 tools, gateway discovered {len(gateway.catalog)}"
            )

        if args.model == "fake":
            model = OracleModel(lambda: current_task[0], args.config)
        else:
            inner = GroqModel(
                api_key=os.environ.get("GROQ_API_KEY") or settings.groq_api_key,
                model=args.llm_model or DEFAULT_MODEL,
            )
            model = CachedModel(inner, args.cache_dir)

        partial = False
        try:
            async with Client(
                gateway.build_server(), elicitation_callback=answer_approval
            ) as client:
                for task in selected:
                    record = await execute_task(
                        task, client, model, gateway, args.config, current_task
                    )
                    with output.open("a", encoding="utf-8") as handle:
                        handle.write(
                            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                        )
                    status = record.get("status")
                    if status == "model_error":
                        partial = True
                        print(
                            f"MODEL ERROR {task['id']}: {record.get('error')} "
                            f"(retry_after={record.get('retry_after')})"
                        )
                        break
                    print(
                        f"{'OK  ' if record['success'] else 'FAIL'} "
                        f"{task['id']:<12} selected={record['selected']}"
                    )
        finally:
            await gateway.stop()

    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = summarize(
        [record for record in records if record.get("status") == "ok"],
        args.config,
        model.name,
        tasks_hash,
        partial,
    )
    summary_path = args.summary or output.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"\n{summary['count']} completed  success={summary['overall']['task_success']:.4f}  "
        f"tool_tokens={summary['overall']['mean_tool_tokens']:.1f}  "
        f"summary={summary_path}"
    )
    return 2 if partial else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=CONFIG_NAMES, required=True)
    parser.add_argument("--model", choices=("fake", "groq"), default="fake")
    parser.add_argument("--llm-model", default=DEFAULT_MODEL)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JSONL output path; required for reproducibility when resuming.",
    )
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--task-ids",
        default="",
        help="Comma-separated task ids for robustness subsets or ablations.",
    )
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.output is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        args.output = DEFAULT_RESULTS / f"{stamp}-{args.config}-{args.model}.jsonl"
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
