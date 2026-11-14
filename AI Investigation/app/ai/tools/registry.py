"""Fixed whitelist of read-only graph investigation tools."""

from __future__ import annotations

import logging
from typing import Any, Iterable, Sequence

from ..providers.base import ToolDefinition
from .definitions import ToolResult, ToolSpec, build_tools
from .graph_client import GraphClient

logger = logging.getLogger("mulegraph.ai.tools")


class ToolRegistry:
    """The only tool surface the model can ever reach.

    The registry is read-only by construction: registering a tool that
    mutates graph state raises, so an LLM can never freeze accounts, transfer
    money, reject transactions or alter the graph - regardless of what it
    generates.
    """

    def __init__(self, tools: Sequence[ToolSpec] | None = None) -> None:
        catalogue = list(tools) if tools is not None else build_tools()
        for spec in catalogue:
            if spec.mutates_graph:  # pragma: no cover - defensive
                raise RuntimeError(
                    f"refusing to register mutating tool {spec.name!r} in the AI registry"
                )
        duplicates = {t.name for t in catalogue if [x.name for x in catalogue].count(t.name) > 1}
        if duplicates:
            raise RuntimeError(f"duplicate tool names: {sorted(duplicates)}")
        self._tools: dict[str, ToolSpec] = {t.name: t for t in catalogue}

    # ------------------------------------------------------------------ #
    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def known_only(self, names: Iterable[str]) -> tuple[list[str], list[str]]:
        """Split requested tool names into (known, unknown)."""
        known, unknown = [], []
        for n in names:
            (known if n in self._tools else unknown).append(n)
        return known, unknown

    # ------------------------------------------------------------------ #
    def definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=spec.name,
                description=spec.description,
                parameters=spec.json_schema(),
            )
            for spec in self._tools.values()
        ]

    def invoke(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        client: GraphClient,
        char_budget: int = 14_000,
    ) -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(
                tool=name,
                arguments=dict(arguments or {}),
                ok=False,
                error=(
                    f"unknown tool {name!r}; available tools: "
                    f"{', '.join(sorted(self._tools))}"
                ),
                error_kind="unknown_tool",
            )
        return spec.invoke(client, arguments, char_budget=char_budget)

    def langchain_tools(self, client: GraphClient) -> list[Any]:
        """LangChain ``StructuredTool`` views (for LangChain-based callers)."""
        return [spec.to_langchain(client) for spec in self._tools.values()]

    def describe(self) -> list[dict[str, str]]:
        return [
            {"name": spec.name, "description": spec.description, "tags": ", ".join(spec.tags)}
            for spec in self._tools.values()
        ]


def build_default_registry() -> ToolRegistry:
    return ToolRegistry()


__all__ = ["ToolRegistry", "build_default_registry"]
