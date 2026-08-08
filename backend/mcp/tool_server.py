"""General MCP surface generated from the canonical SpectrumClaw tool registry."""

from __future__ import annotations

import os

from ..tools.mcp_adapter import register_mcp_tools


def build_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - depends on deployment extras
        raise RuntimeError("当前 Python 环境未安装 MCP SDK") from exc

    server = FastMCP(
        "SpectrumClaw Tools",
        instructions=(
            "提供 SpectrumClaw 明确允许外部发现的只读知识、频率规划、天气和搜索工具。"
            "未标记为 MCP 的系统状态、URL 抓取、底层控制和 UAV 工具不会在此服务公开。"
        ),
        json_response=True,
    )
    register_mcp_tools(server)
    return server


def main() -> None:
    transport = os.environ.get("SPECTRUMCLAW_TOOL_MCP_TRANSPORT", "stdio").strip().lower()
    if transport not in {"stdio", "streamable-http", "sse"}:
        raise SystemExit("SPECTRUMCLAW_TOOL_MCP_TRANSPORT 必须是 stdio、streamable-http 或 sse")
    build_server().run(transport=transport)


if __name__ == "__main__":
    main()
