from __future__ import annotations

import asyncio
import json
import time


def test_tool_spec_is_the_single_schema_source():
    from backend.tools.contracts import ToolExposure, ToolSpec

    def echo(value: str) -> str:
        return value

    spec = ToolSpec(
        name="unit_contract_echo",
        description="Echo one value",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        handler=echo,
        category="test",
        exposure=ToolExposure(mcp=True),
        timeout_s=1.0,
    )

    assert spec.openai_schema() == {
        "type": "function",
        "function": {
            "name": "unit_contract_echo",
            "description": "Echo one value",
            "parameters": spec.parameters,
        },
    }
    assert spec.exposure.native is True
    assert spec.exposure.mcp is True


def test_registry_stores_tool_specs_and_preserves_compatibility_accessors():
    from backend.tools.contracts import ToolSpec
    from backend.tools.registry import get_handler, get_schema, get_spec, register

    handler = lambda value="ok": value
    registered = register(
        "unit_registry_echo",
        handler,
        "Echo",
        {"type": "object", "properties": {"value": {"type": "string"}}},
        "test",
    )

    assert isinstance(registered, ToolSpec)
    assert get_spec("unit_registry_echo") is registered
    assert get_handler("unit_registry_echo") is handler
    assert get_schema("unit_registry_echo")["function"]["name"] == "unit_registry_echo"


def test_runtime_executes_sync_and_async_tools():
    from backend.tools.registry import register
    from backend.tools.runtime import ToolRuntime

    register(
        "unit_sync_add",
        lambda left, right: left + right,
        "Add",
        {"type": "object", "properties": {}},
        "test",
    )

    async def async_echo(value: str) -> dict:
        return {"value": value}

    register(
        "unit_async_echo",
        async_echo,
        "Echo",
        {"type": "object", "properties": {}},
        "test",
    )

    runtime = ToolRuntime()
    assert asyncio.run(runtime.invoke("unit_sync_add", {"left": 2, "right": 3})) == 5
    assert asyncio.run(runtime.invoke("unit_async_echo", {"value": "ready"})) == {"value": "ready"}


def test_runtime_wraps_unknown_errors_and_timeouts_as_json():
    from backend.tools.registry import register
    from backend.tools.runtime import ToolRuntime

    def explode():
        raise RuntimeError("boom")

    async def wait_forever():
        await asyncio.sleep(0.05)

    register("unit_explode", explode, "Explode", {"type": "object", "properties": {}}, "test")
    register(
        "unit_timeout",
        wait_forever,
        "Timeout",
        {"type": "object", "properties": {}},
        "test",
        timeout_s=0.001,
    )

    runtime = ToolRuntime()
    unknown = json.loads(asyncio.run(runtime.execute_json("unit_missing", {})))
    failed = json.loads(asyncio.run(runtime.execute_json("unit_explode", {})))
    timed_out = json.loads(asyncio.run(runtime.execute_json("unit_timeout", {})))

    assert unknown == {"error": "Unknown tool: unit_missing", "code": "tool_not_found"}
    assert failed == {"error": "boom", "code": "tool_execution_error", "tool": "unit_explode"}
    assert timed_out["code"] == "tool_timeout"
    assert timed_out["tool"] == "unit_timeout"


def test_runtime_validates_required_enum_and_number_bounds():
    from backend.tools.registry import register
    from backend.tools.runtime import ToolRuntime

    register(
        "unit_validated",
        lambda mode, count: {"mode": mode, "count": count},
        "Validated",
        {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["safe"]},
                "count": {"type": "integer", "minimum": 1, "maximum": 3},
            },
            "required": ["mode", "count"],
        },
        "test",
    )

    runtime = ToolRuntime()
    missing = json.loads(asyncio.run(runtime.execute_json("unit_validated", {"mode": "safe"})))
    invalid = json.loads(asyncio.run(runtime.execute_json("unit_validated", {"mode": "raw", "count": 4})))

    assert missing["code"] == "tool_validation_error"
    assert "count" in missing["error"]
    assert invalid["code"] == "tool_validation_error"


def test_runtime_applies_timeout_to_sync_handlers():
    from backend.tools.registry import register
    from backend.tools.runtime import ToolRuntime

    def slow_sync():
        time.sleep(0.05)
        return "late"

    register(
        "unit_sync_timeout",
        slow_sync,
        "Slow sync",
        {"type": "object", "properties": {}},
        "test",
        timeout_s=0.001,
    )

    result = json.loads(asyncio.run(ToolRuntime().execute_json("unit_sync_timeout", {})))
    assert result["code"] == "tool_timeout"
