from __future__ import annotations

import asyncio


def test_legacy_llm_registration_delegates_to_unified_registry():
    from backend.llm.client import get_tool_schemas, register_tool
    from backend.tools.registry import get_spec

    handler = lambda value="ok": value
    schema = {
        "name": "unit_llm_registry_echo",
        "description": "Echo",
        "parameters": {"type": "object", "properties": {"value": {"type": "string"}}},
    }
    register_tool("unit_llm_registry_echo", handler, schema)

    spec = get_spec("unit_llm_registry_echo")
    assert spec is not None
    assert spec.handler is handler
    assert get_tool_schemas(["unit_llm_registry_echo"]) == [
        {"type": "function", "function": schema}
    ]


def test_llm_execution_and_langchain_use_the_same_tool_spec():
    from backend.llm.client import _execute_tools, register_tool
    from backend.tools.langchain_tools import build_langchain_tool

    register_tool(
        "unit_shared_adapter",
        lambda value: {"value": value},
        {
            "name": "unit_shared_adapter",
            "description": "Shared adapter",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
    )

    messages = asyncio.run(_execute_tools([{
        "id": "call_shared",
        "type": "function",
        "function": {"name": "unit_shared_adapter", "arguments": '{"value":"same"}'},
    }]))
    langchain_result = asyncio.run(build_langchain_tool("unit_shared_adapter").ainvoke({"value": "same"}))

    assert '"same"' in messages[0]["content"]
    assert langchain_result == {"value": "same"}


def test_default_registration_uses_unified_registry():
    from backend.llm.tools import register_default_tools
    from backend.tools.registry import get_spec

    register_default_tools()

    assert get_spec("get_time") is not None
    assert get_spec("search_knowledge_base") is not None
