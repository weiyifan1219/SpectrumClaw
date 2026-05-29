"""Convert unified tool registry entries to LangChain StructuredTool objects."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.tools import StructuredTool

from .registry import get_all_schemas, get_handler, TOOL_REGISTRY


def _make_sync_wrapper(async_handler):
    """Wrap an async handler for LangChain's sync invocation."""
    def sync_fn(**kwargs):
        return asyncio.run(async_handler(**kwargs))
    return sync_fn


def _make_async_wrapper(sync_handler):
    """Wrap a sync handler for LangChain's async invocation."""
    async def async_fn(**kwargs):
        return sync_handler(**kwargs)
    return async_fn


def build_langchain_tool(name: str) -> StructuredTool | None:
    """Build a single LangChain StructuredTool from the unified registry."""
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        return None

    handler = entry["handler"]
    is_async = asyncio.iscoroutinefunction(handler)

    return StructuredTool.from_function(
        func=_make_sync_wrapper(handler) if is_async else handler,
        coroutine=handler if is_async else _make_async_wrapper(handler),
        name=entry["name"],
        description=entry["description"],
        args_schema=None,  # use function signature
    )


def build_all_langchain_tools() -> list[StructuredTool]:
    """Build LangChain StructuredTool objects for all registered tools."""
    tools = []
    for name in TOOL_REGISTRY:
        tool = build_langchain_tool(name)
        if tool:
            tools.append(tool)
    return tools


def get_langchain_tools_for(names: list[str]) -> list[StructuredTool]:
    """Build LangChain tools for specific tool names."""
    tools = []
    for name in names:
        tool = build_langchain_tool(name)
        if tool:
            tools.append(tool)
    return tools
