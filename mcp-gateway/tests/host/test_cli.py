"""Tests for the host CLI helpers."""

from __future__ import annotations

import pytest
from mcp.types import Tool

from src.host.cli import parse_arguments, parse_value, search_tools
from tests.fakes import demo_tools


def test_parse_value_accepts_json_and_falls_back_to_text() -> None:
    assert parse_value("3") == 3
    assert parse_value("true") is True
    assert parse_value('{"a": 1}') == {"a": 1}
    assert parse_value("api") == "api"


def test_parse_arguments_rejects_malformed_pairs() -> None:
    assert parse_arguments(["limit=2", "query=SSRF"]) == {"limit": 2, "query": "SSRF"}
    with pytest.raises(ValueError, match="key=value"):
        parse_arguments(["limit"])
    with pytest.raises(ValueError, match="empty key"):
        parse_arguments(["=2"])


def test_search_tools_ranks_metadata() -> None:
    tools: list[Tool] = demo_tools()
    matches = search_tools(tools, "restart service", 3)
    assert matches[0].name == "restart_service"
    assert search_tools(tools, "zzzz", 3) == []


def test_tool_summary_marks_meta_tools() -> None:
    from src.gateway.router import FIND_TOOLS, INVOKE_TOOL
    from src.host.cli import _tool_summary

    assert _tool_summary(FIND_TOOLS)["risk"] == "read"
    assert _tool_summary(INVOKE_TOOL)["risk"] == "write"
