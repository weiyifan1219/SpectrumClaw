from __future__ import annotations

import asyncio


class FakeMcpServer:
    def __init__(self) -> None:
        self.tools: dict[str, dict] = {}

    def tool(self, *, name: str, description: str):
        def decorator(handler):
            self.tools[name] = {"description": description, "handler": handler}
            return handler

        return decorator


def test_mcp_adapter_registers_only_explicitly_exposed_specs():
    from backend.tools.contracts import ToolExposure, ToolSpec
    from backend.tools.mcp_adapter import register_mcp_tools

    native_only = ToolSpec(
        name="unit_native_only",
        description="Native only",
        parameters={"type": "object", "properties": {}},
        handler=lambda: "private",
    )
    shared = ToolSpec(
        name="unit_shared_mcp",
        description="Shared over MCP",
        parameters={"type": "object", "properties": {}},
        handler=lambda: {"ok": True},
        exposure=ToolExposure(mcp=True),
    )
    registry = {native_only.name: native_only, shared.name: shared}
    server = FakeMcpServer()

    registered = register_mcp_tools(server, registry=registry)

    assert registered == ("unit_shared_mcp",)
    assert set(server.tools) == {"unit_shared_mcp"}
    assert server.tools["unit_shared_mcp"]["description"] == "Shared over MCP"
    assert asyncio.run(server.tools["unit_shared_mcp"]["handler"]()) == {"ok": True}


def test_builtin_mcp_surface_excludes_private_and_low_level_tools():
    from backend.tools.mcp_adapter import register_mcp_tools
    from backend.tools.registry import register_all

    register_all()
    server = FakeMcpServer()
    registered = set(register_mcp_tools(server))

    assert registered == {
        "get_weather",
        "web_search",
        "search_knowledge_base",
        "plan_frequency",
    }
    assert "get_system_status" not in registered
    assert "web_fetch" not in registered
    assert "control_uav_simulation" not in registered
    assert "execute_uav_mission_plan" not in registered
