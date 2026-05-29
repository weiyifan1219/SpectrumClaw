"""Tool execution helpers — execute tools by name, with error wrapping."""

from __future__ import annotations

import asyncio
import json as _json
from typing import Any

from .registry import get_handler, TOOL_REGISTRY


async def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Execute a single tool by name. Returns JSON string (success or error)."""
    handler = get_handler(name)
    if not handler:
        return _json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)

    try:
        if asyncio.iscoroutinefunction(handler):
            result = await handler(**arguments)
        else:
            result = handler(**arguments)

        if isinstance(result, str):
            return result
        return _json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return _json.dumps({"error": str(exc)}, ensure_ascii=False)


async def execute_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """Execute multiple tool calls, return tool result messages."""
    import json as _json
    results = []
    for tc in tool_calls:
        fn_name = tc["function"]["name"]
        try:
            fn_args = _json.loads(tc["function"]["arguments"])
        except (_json.JSONDecodeError, KeyError):
            fn_args = {}
        content = await execute_tool(fn_name, fn_args)
        results.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": content,
        })
    return results
