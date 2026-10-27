"""Tests for task predicates, meta-tool unwrapping and corpus validation."""

from __future__ import annotations

from typing import Any

from eval.run_eval import actual_selection, predicate_matches
from eval.validate_tasks import validate
from src.gateway.router import META_TOOLS
from src.host.llm import OracleModel, ToolCall


def test_predicates_cover_paths_and_text() -> None:
    output = {"count": 5, "status": "open", "points": [1, 2, 3]}
    assert predicate_matches({"type": "contains", "value": "open"}, output, "")
    assert predicate_matches(
        {"type": "path_equals", "path": "status", "value": "open"}, output, ""
    )
    assert predicate_matches(
        {"type": "path_min", "path": "count", "value": 5}, output, ""
    )
    assert predicate_matches(
        {"type": "path_len", "path": "points", "value": 3}, output, ""
    )
    assert not predicate_matches(
        {"type": "path_equals", "path": "status", "value": "closed"}, output, ""
    )


def test_nested_predicates() -> None:
    output = {"service": "api", "points": [1, 2]}
    predicate = {
        "type": "all",
        "predicates": [
            {"type": "path_equals", "path": "service", "value": "api"},
            {"type": "path_len", "path": "points", "value": 2},
        ],
    }
    assert predicate_matches(predicate, output, "")


def test_actual_selection_unwraps_invoke_tool() -> None:
    call = ToolCall(
        id="1",
        name="invoke_tool",
        arguments={
            "server": "docs-mcp",
            "tool": "search_docs",
            "arguments": {"query": "mcp"},
        },
    )
    assert actual_selection(call) == ("docs__search_docs", {"query": "mcp"})
    find_call = ToolCall(id="2", name="find_tools", arguments={"query": "x"})
    assert actual_selection(find_call) is None


async def test_oracle_model_uses_invoke_tool_in_meta_mode() -> None:
    task: dict[str, Any] = {
        "id": "t1",
        "query": "search docs",
        "gold": {"server": "docs", "tool": "search_docs", "arguments": {"query": "x"}},
    }
    model = OracleModel(lambda: task, "meta")
    response = await model.complete([], META_TOOLS)
    assert response.tool_calls[0].name == "invoke_tool"
    assert response.tool_calls[0].arguments["server"] == "docs"


async def test_oracle_model_abstains_on_negative_task() -> None:
    task: dict[str, Any] = {
        "id": "neg",
        "query": "draw a cat",
        "gold": None,
    }
    model = OracleModel(lambda: task, "static")
    response = await model.complete([], [])
    assert response.tool_calls == []


async def test_frozen_corpus_matches_real_schemas() -> None:
    await validate()
