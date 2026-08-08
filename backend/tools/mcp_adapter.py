"""Expose explicitly allowed ToolSpecs through a FastMCP-compatible server."""

from __future__ import annotations

from functools import wraps
from typing import Any

from .contracts import ToolSpec
from .runtime import ToolRuntime


def _runtime_handler(spec: ToolSpec, runtime: ToolRuntime):
    @wraps(spec.handler)
    async def invoke(**arguments: Any):
        return await runtime.invoke(spec.name, arguments, surface="mcp")

    return invoke


def register_mcp_tools(server, *, registry: dict[str, ToolSpec] | None = None) -> tuple[str, ...]:
    """Register the MCP-enabled subset of a canonical tool registry."""
    if registry is None:
        from .registry import TOOL_REGISTRY, register_all

        register_all()
        registry = TOOL_REGISTRY

    runtime = ToolRuntime(registry)
    registered: list[str] = []
    for spec in registry.values():
        if not spec.exposure.mcp:
            continue
        server.tool(name=spec.name, description=spec.description)(
            _runtime_handler(spec, runtime)
        )
        registered.append(spec.name)
    return tuple(registered)
