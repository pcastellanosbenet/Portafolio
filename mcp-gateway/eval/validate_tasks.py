"""Validate the frozen evaluation corpus against the real upstream schemas."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema

from src.upstreams.docs.server import mcp as docs_server
from src.upstreams.ops.server import mcp as ops_server
from src.upstreams.research.server import mcp as research_server

ROOT = Path(__file__).parent
TASKS_PATH = ROOT / "tasks.jsonl"
HASH_PATH = ROOT / "tasks.sha256"
SUCCESS_TYPES = {"contains", "path_equals", "path_min", "path_len", "all", "abstain"}


async def tool_schemas() -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for name, server in (
        ("docs", docs_server),
        ("research", research_server),
        ("ops", ops_server),
    ):
        result = await server.list_tools()
        for tool in result:
            schemas[f"{name}__{tool.name}"] = tool.input_schema
    return schemas


def load_tasks() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in TASKS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def validate() -> None:
    tasks = load_tasks()
    assert len(tasks) == 60
    assert len({task["id"] for task in tasks}) == 60
    counts = {
        block: sum(1 for task in tasks if task["block"] == block)
        for block in ("docs", "research", "ops", "negative")
    }
    assert counts == {"docs": 20, "research": 15, "ops": 15, "negative": 10}

    schemas = await tool_schemas()
    assert len(schemas) == 22
    for task in tasks:
        assert task["success"]["type"] in SUCCESS_TYPES, task["id"]
        if task["block"] == "negative":
            assert task["gold"] is None
            assert task["success"] == {"type": "abstain"}
            continue
        gold = task["gold"]
        assert gold is not None
        name = f"{gold['server']}__{gold['tool']}"
        assert name in schemas, f"{task['id']}: unknown tool {name}"
        jsonschema.Draft202012Validator(schemas[name]).validate(gold["arguments"])

    digest = hashlib.sha256(TASKS_PATH.read_bytes()).hexdigest()
    expected = HASH_PATH.read_text(encoding="utf-8").split()[0]
    assert digest == expected, "tasks.jsonl changed without regenerating the hash"
    print(f"validated 60 tasks, {len(schemas)} tool schemas, sha256={digest}")


if __name__ == "__main__":
    asyncio.run(validate())
