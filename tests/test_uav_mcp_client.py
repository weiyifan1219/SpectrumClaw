"""Tests for the managed MCP client policy boundary."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest


def test_client_rejects_unknown_or_raw_flight_tool_before_transport():
    from backend.mcp.client import ManagedUavMcpClient

    async def run():
        client = ManagedUavMcpClient(session_factory=lambda: None)
        with pytest.raises(ValueError, match="不允许"):
            await client.call_tool("raw_mavlink", {})

    asyncio.run(run())


def test_client_calls_allowlisted_mcp_tool_with_structured_result():
    from backend.mcp.client import ManagedUavMcpClient

    calls: list[tuple[str, dict]] = []

    class Session:
        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            return {"ok": True, "content": "safe"}

    @asynccontextmanager
    async def session_factory():
        yield Session()

    async def run():
        client = ManagedUavMcpClient(session_factory=session_factory)
        result = await client.call_tool("uav_list_templates", {})
        assert result == {"ok": True, "content": "safe"}

    asyncio.run(run())

    assert calls == [("uav_list_templates", {})]


def test_uav_mcp_is_opt_in_and_stdio_only_by_default(monkeypatch):
    from backend.config import get_settings

    monkeypatch.delenv("SPECTRUMCLAW_UAV_MCP_ENABLED", raising=False)
    monkeypatch.delenv("SPECTRUMCLAW_UAV_MCP_TRANSPORT", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.uav_mcp_enabled is False
    assert settings.uav_mcp_transport == "stdio"
