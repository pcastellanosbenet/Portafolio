"""Tests for catalog namespacing, pinning and collision handling."""

from __future__ import annotations

import pytest
from mcp.types import Tool

from src.gateway.catalog import Catalog, CatalogError
from src.models import RiskLevel
from tests.fakes import demo_tools, make_tool


def test_registers_25_tools_with_namespaced_names() -> None:
    catalog = Catalog()
    descriptors = catalog.register("docs", demo_tools(25))

    assert len(catalog) == 25
    assert len(descriptors) == 25
    assert all(descriptor.name.startswith("docs__") for descriptor in descriptors)
    assert [descriptor.name for descriptor in descriptors] == sorted(
        descriptor.name for descriptor in descriptors
    )


def test_definition_hash_is_stable_and_changes_with_content() -> None:
    first = Catalog()
    second = Catalog()
    first.register("docs", [make_tool("search", "Search.")])
    second.register("docs", [make_tool("search", "Search.")])

    first_hash = first.descriptors()[0].definition_hash
    assert first_hash == second.descriptors()[0].definition_hash

    changed = Catalog()
    changed.register("docs", [make_tool("search", "Search differently.")])
    assert changed.descriptors()[0].definition_hash != first_hash


def test_risk_is_inferred_from_annotations() -> None:
    catalog = Catalog()
    catalog.register(
        "ops",
        [
            make_tool("read", read_only=True),
            make_tool("write", read_only=False),
            make_tool("destroy", read_only=False, destructive=True),
        ],
    )
    by_name = {descriptor.original_name: descriptor for descriptor in catalog.descriptors()}
    assert by_name["read"].risk is RiskLevel.READ
    assert by_name["write"].risk is RiskLevel.WRITE
    assert by_name["destroy"].risk is RiskLevel.DESTRUCTIVE


def test_duplicate_tool_names_are_rejected_atomically() -> None:
    catalog = Catalog()
    with pytest.raises(CatalogError, match="duplicate tool name"):
        catalog.register("docs", [make_tool("search"), make_tool("search")])
    assert len(catalog) == 0


def test_invalid_input_schema_is_rejected() -> None:
    catalog = Catalog()
    broken = Tool(name="broken", inputSchema={"type": "not-a-json-type"})
    with pytest.raises(CatalogError, match="invalid schema"):
        catalog.register("docs", [broken])


def test_replace_rolls_back_on_collision() -> None:
    catalog = Catalog()
    catalog.register("docs", [make_tool("search")])
    with pytest.raises(CatalogError):
        catalog.replace("docs", [make_tool("search"), make_tool("search")])
    assert len(catalog) == 1


def test_names_longer_than_64_characters_are_rejected() -> None:
    catalog = Catalog()
    with pytest.raises(CatalogError, match="1-64 characters"):
        catalog.register("docs", [make_tool("x" * 60)])


def test_unregister_removes_only_one_upstream() -> None:
    catalog = Catalog()
    catalog.register("docs", [make_tool("search")])
    catalog.register("ops", [make_tool("restart")])
    catalog.unregister("docs")
    assert [descriptor.name for descriptor in catalog.descriptors()] == ["ops__restart"]
