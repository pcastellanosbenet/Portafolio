"""Host CLI for the MCP gateway."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
from typing import Any

import httpx
from mcp import Client
from mcp.types import ElicitRequestParams, ElicitResult, Tool
from rank_bm25 import BM25Okapi

from src.gateway.router import QUERY_META_KEY

TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokens(text: str) -> list[str]:
    """Tokenize tool metadata for local search."""
    return TOKEN_RE.findall(text.lower())


def parse_value(raw: str) -> Any:
    """Parse a JSON scalar/object, falling back to a plain string."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_arguments(pairs: list[str]) -> dict[str, Any]:
    """Parse repeated `--arg key=value` flags."""
    arguments: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"argument must use key=value: {pair}")
        key, raw = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"argument has an empty key: {pair}")
        arguments[key] = parse_value(raw)
    return arguments


def search_tools(tools: list[Tool], query: str, limit: int = 8) -> list[Tool]:
    """Rank tools with BM25 over names, titles and descriptions."""
    query_tokens = tokens(query)
    if not query_tokens or not tools:
        return []
    corpus = [
        tokens(f"{tool.name} {tool.title or ''} {tool.description or ''}")
        for tool in tools
    ]
    scores = BM25Okapi(corpus).get_scores(query_tokens)
    ranked = sorted(zip(tools, scores, strict=True), key=lambda item: (-item[1], item[0].name))
    return [tool for tool, score in ranked[: max(1, limit)] if score > 0]


def _tool_summary(tool: Tool) -> dict[str, Any]:
    if tool.name == "find_tools":
        risk = "read"
    elif tool.name == "invoke_tool":
        risk = "write"
    else:
        risk = (
            "destructive"
            if tool.annotations and tool.annotations.destructive_hint
            else "read"
            if tool.annotations and tool.annotations.read_only_hint
            else "write"
        )
    return {
        "name": tool.name,
        "title": tool.title,
        "description": tool.description,
        "risk": risk,
        "input_schema": tool.input_schema,
    }


async def remote_tools(url: str, query: str | None = None) -> list[Tool]:
    """Fetch the catalog from a running gateway, optionally for a hybrid query."""
    meta = {QUERY_META_KEY: query} if query else None
    async with Client(url) as client:
        response = await client.list_tools(meta=meta)
    return response.tools


def print_tools(tools: list[Tool], as_json: bool) -> None:
    """Print a compact tool table or JSON."""
    if as_json:
        print(json.dumps([_tool_summary(tool) for tool in tools], indent=2, ensure_ascii=False))
        return
    if not tools:
        print("No tools found.")
        return
    width = max(len(tool.name) for tool in tools)
    for tool in tools:
        summary = _tool_summary(tool)
        description = (summary["description"] or "").splitlines()[0]
        print(f"{tool.name:<{width}}  {summary['risk']:<11}  {description}")


async def command_tools(args: argparse.Namespace) -> int:
    tools = await remote_tools(args.url, args.query)
    print_tools(tools, args.json)
    return 0


async def command_search(args: argparse.Namespace) -> int:
    tools = await remote_tools(args.url)
    matches = search_tools(tools, args.query, args.limit)
    print_tools(matches, args.json)
    return 0


async def command_call(args: argparse.Namespace) -> int:
    arguments = parse_arguments(args.arg)

    async def answer_approval(
        _context: Any, params: ElicitRequestParams
    ) -> ElicitResult:
        message = getattr(params, "message", str(params))
        if args.reject:
            print(f"approval declined (--reject): {message}", file=sys.stderr)
            return ElicitResult(action="decline", content=None)
        if args.approve:
            print(f"approval accepted (--approve): {message}", file=sys.stderr)
            return ElicitResult(action="accept", content={"approve": True})
        if not sys.stdin.isatty():
            print(
                f"approval required: {message}\n"
                "No interactive terminal; rerun with --approve to allow it.",
                file=sys.stderr,
            )
            return ElicitResult(action="decline", content=None)
        answer = input(f"{message} [y/N] ").strip().lower()
        approved = answer in {"y", "yes", "s", "si", "sí"}
        return ElicitResult(
            action="accept" if approved else "decline",
            content={"approve": True} if approved else None,
        )

    async with Client(args.url, elicitation_callback=answer_approval) as client:
        if args.query:
            await client.list_tools(meta={QUERY_META_KEY: args.query})
        result = await client.call_tool(args.tool, arguments)
    trace_id = (result.meta or {}).get("trace_id")
    if args.json:
        payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        payload["trace_id"] = trace_id
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        if result.structured_content is not None:
            print(json.dumps(result.structured_content, indent=2, ensure_ascii=False))
        else:
            for item in result.content:
                if item.type == "text":
                    print(item.text)
        print(f"\ntrace_id: {trace_id or 'unavailable'}")
        if result.is_error:
            print("status: error")
    if result.is_error:
        return 2
    return 0


def open_audit(db_path: str) -> sqlite3.Connection:
    """Open the audit database read-only."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"audit database not found: {db_path}")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def command_trace(args: argparse.Namespace) -> int:
    connection = open_audit(args.db)
    try:
        rows = connection.execute(
            """
            SELECT trace_id, server, tool, status, latency_ms, client_name, created_at, error
            FROM calls
            WHERE (? IS NULL OR trace_id = ?)
            ORDER BY id DESC LIMIT ?
            """,
            (args.trace_id, args.trace_id, args.limit),
        ).fetchall()
    finally:
        connection.close()
    columns = [
        "trace_id",
        "server",
        "tool",
        "status",
        "latency_ms",
        "client_name",
        "created_at",
        "error",
    ]
    records = [dict(zip(columns, row, strict=True)) for row in rows]
    if args.json:
        print(json.dumps(records, indent=2, ensure_ascii=False))
        return 0
    if not records:
        print("No audit records.")
        return 0
    for record in records:
        error = f"  error={record['error'][:80]}" if record["error"] else ""
        print(
            f"{record['trace_id'][:12]}  {record['created_at']}  "
            f"{record['status']:<16}  {record['latency_ms']:>7.2f} ms  "
            f"{record['tool']}{error}"
        )
    return 0


async def command_health(args: argparse.Namespace) -> int:
    url = args.url.rstrip("/").removesuffix("/mcp") + "/health"
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url)
        response.raise_for_status()
    payload = response.json()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload.get("status") == "ok" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-gateway-host",
        description="List, search, call and trace tools exposed by the MCP gateway.",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("GATEWAY_PUBLIC_URL", "http://127.0.0.1:8765/mcp"),
        help="Gateway Streamable HTTP URL.",
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("GATEWAY_DB_PATH", "artifacts/gateway.db"),
        help="Gateway audit SQLite path (used by the trace command).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    tools = subparsers.add_parser("tools", help="List the aggregated catalog.")
    tools.add_argument(
        "--query",
        default=None,
        help="Task query for hybrid listings; ignored by static/meta modes.",
    )
    tools.add_argument("--json", action="store_true")
    tools.set_defaults(handler=command_tools)

    search = subparsers.add_parser("search", help="Search tools locally with BM25.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=command_search)

    call = subparsers.add_parser("call", help="Invoke one namespaced tool.")
    call.add_argument("tool")
    call.add_argument(
        "--arg",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Tool argument; repeat for multiple values. JSON values are parsed.",
    )
    call.add_argument("--json", action="store_true")
    call.add_argument(
        "--query",
        default=None,
        help="Task query used to refresh a hybrid tools/list before calling.",
    )
    approval = call.add_mutually_exclusive_group()
    approval.add_argument(
        "--approve",
        action="store_true",
        help="Accept a destructive action without an interactive prompt.",
    )
    approval.add_argument(
        "--reject",
        action="store_true",
        help="Decline a destructive action without an interactive prompt.",
    )
    call.set_defaults(handler=command_call)

    trace = subparsers.add_parser("trace", help="Read recent audit records.")
    trace.add_argument("--trace-id")
    trace.add_argument("--limit", type=int, default=20)
    trace.add_argument("--json", action="store_true")
    trace.set_defaults(handler=None)

    health = subparsers.add_parser("health", help="Read the gateway health endpoint.")
    health.set_defaults(handler=command_health)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "trace":
            return command_trace(args)
        return asyncio.run(args.handler(args))
    except (ValueError, FileNotFoundError, httpx.HTTPError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
