"""Managed MCP client for the allowlisted UAV server.

The client is deliberately narrow: it can connect only to the local
SpectrumClaw UAV MCP child process and call only its public task-level tools.
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

from .uav_contract import MCP_UAV_TOOL_NAMES


SessionFactory = Callable[[], AsyncIterator[Any]]


class ManagedUavMcpClient:
    """Lifecycle-managed, tool-allowlisted client for one local MCP server."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        timeout_s: float = 12.0,
        python_executable: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._timeout_s = timeout_s
        self._python_executable = python_executable or os.environ.get("SPECTRUMCLAW_UAV_MCP_PYTHON", sys.executable)

    @asynccontextmanager
    async def _open_stdio_session(self) -> AsyncIterator[Any]:
        """Start the MCP server as a local child only when a call is needed."""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:  # pragma: no cover - exercised on deployed host
            raise RuntimeError("当前 Python 环境未安装 MCP SDK") from exc
        params = StdioServerParameters(
            command=self._python_executable,
            args=["-m", "backend.mcp.uav_server"],
            cwd=str(_project_root()),
            env={**os.environ, "SPECTRUMCLAW_UAV_MCP_TRANSPORT": "stdio"},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in MCP_UAV_TOOL_NAMES:
            raise ValueError(f"不允许通过 UAV MCP 调用工具：{name}")
        factory = self._session_factory or self._open_stdio_session
        async with factory() as session:
            result = await asyncio.wait_for(
                session.call_tool(name, arguments),
                timeout=self._timeout_s,
            )
        return result.model_dump() if hasattr(result, "model_dump") else result


def _project_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[2]
