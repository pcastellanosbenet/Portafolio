"""Tool catalog: discovery, namespacing and definition pinning."""

from __future__ import annotations

import jsonschema
from mcp.types import Tool

from src.models import ToolDescriptor, make_descriptor


class CatalogError(Exception):
    """Raised when an upstream cannot be registered safely."""


class Catalog:
    """In-memory catalog of namespaced tools from all connected upstreams."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDescriptor] = {}

    def register(self, server: str, tools: list[Tool]) -> list[ToolDescriptor]:
        """Register an upstream's tools atomically, rejecting collisions or bad schemas."""
        pending: dict[str, ToolDescriptor] = {}
        for tool in tools:
            try:
                descriptor = make_descriptor(server, tool)
            except ValueError as exc:
                raise CatalogError(str(exc)) from exc
            if descriptor.name in self._tools or descriptor.name in pending:
                raise CatalogError(f"duplicate tool name: {descriptor.name}")
            try:
                jsonschema.Draft202012Validator.check_schema(tool.input_schema)
            except jsonschema.SchemaError as exc:
                raise CatalogError(f"invalid schema for {descriptor.name}: {exc.message}") from exc
            pending[descriptor.name] = descriptor

        self._tools.update(pending)
        return sorted(pending.values(), key=lambda descriptor: descriptor.name)

    def replace(self, server: str, tools: list[Tool]) -> list[ToolDescriptor]:
        """Replace every tool from one upstream, keeping the operation atomic."""
        previous = {
            name: descriptor
            for name, descriptor in self._tools.items()
            if descriptor.server == server
        }
        for name in previous:
            del self._tools[name]
        try:
            return self.register(server, tools)
        except CatalogError:
            self._tools.update(previous)
            raise

    def unregister(self, server: str) -> None:
        """Remove every tool from an upstream."""
        for name in [
            name for name, descriptor in self._tools.items() if descriptor.server == server
        ]:
            del self._tools[name]

    def get(self, name: str) -> ToolDescriptor | None:
        """Return a descriptor by its canonical name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """Return tools in deterministic order for cache-friendly listings."""
        return [
            descriptor.tool
            for descriptor in sorted(self._tools.values(), key=lambda item: item.name)
        ]

    def descriptors(self) -> list[ToolDescriptor]:
        """Return every descriptor in deterministic order."""
        return sorted(self._tools.values(), key=lambda item: item.name)

    def by_server(self) -> dict[str, list[ToolDescriptor]]:
        """Group descriptors by upstream, in deterministic order."""
        grouped: dict[str, list[ToolDescriptor]] = {}
        for descriptor in self.descriptors():
            grouped.setdefault(descriptor.server, []).append(descriptor)
        return grouped

    def __len__(self) -> int:
        return len(self._tools)
