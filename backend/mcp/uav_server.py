"""Standard MCP surface for the simulator-only UAV task adapter.

Run locally through stdio by default.  A Streamable HTTP deployment is also
supported for a loopback-only service or an authenticated gateway; neither
transport is allowed to bypass :mod:`backend.skills.uav_spectrum_sim.mission`.
"""

from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

from ..skills.uav_spectrum_sim.contracts import MissionPlan, build_mission_plan
from ..skills.uav_spectrum_sim.mission import get_uav_mission_service
from ..skills.uav_spectrum_sim.templates import list_templates
from .uav_contract import capability_document


mcp = FastMCP(
    "SpectrumClaw UAV Simulation",
    instructions=(
        "仅控制当前 SpectrumClaw PX4/Gazebo 仿真。"
        "先查询 uav_get_state；飞行前需有明确用户意图。"
        "不可用于真实飞行器，也不可发送任意 MAVLink 或速度指令。"
    ),
    json_response=True,
)


@mcp.tool()
def uav_get_state() -> dict:
    """读取仿真、人工接管、真实位姿和允许的任务状态；不会控制飞行器。"""
    return get_uav_mission_service().inspect()


@mcp.tool()
def uav_list_templates() -> list[dict]:
    """列出可从自然语言任务映射的固定安全模板。"""
    return list_templates()


def _plan(
    mission_id: str,
    template: str,
    landmark: str | None,
    altitude_m: float | None,
    expires_in_s: float,
) -> MissionPlan:
    return build_mission_plan(mission_id, template, landmark, altitude_m, expires_in_s)


@mcp.tool()
def uav_validate_plan(
    mission_id: str,
    template: str,
    landmark: str | None = None,
    altitude_m: float | None = None,
    expires_in_s: float = 120.0,
) -> dict:
    """验证声明式任务计划；不产生任何飞行控制。"""
    plan = _plan(mission_id, template, landmark, altitude_m, expires_in_s)
    service = get_uav_mission_service()
    decision = service._policy.validate(plan, service._status_reader())
    return {"plan": plan.model_dump(), "decision": decision.model_dump()}


@mcp.tool()
def uav_execute_plan(
    mission_id: str,
    template: str,
    landmark: str | None = None,
    altitude_m: float | None = None,
    expires_in_s: float = 120.0,
) -> dict:
    """执行经过策略门控的任务计划；不能传入原始位置或 MAVLink 字段。"""
    return get_uav_mission_service().execute_plan(
        _plan(mission_id, template, landmark, altitude_m, expires_in_s)
    )


@mcp.tool()
def uav_cancel_mission() -> dict:
    """取消当前智能体任务并让 PX4/Gazebo 仿真无人机悬停。"""
    return get_uav_mission_service().cancel()


@mcp.tool()
def uav_get_run_events() -> list[dict]:
    """返回公开的执行、观测与安全审计事件。"""
    return get_uav_mission_service().recent_events()


@mcp.resource("spectrumclaw://uav/capabilities")
def uav_capabilities() -> str:
    """Return a machine-readable safety contract for MCP hosts."""
    return json.dumps(capability_document(), ensure_ascii=False)


@mcp.resource("spectrumclaw://uav/safety-policy")
def uav_safety_policy() -> str:
    return json.dumps(capability_document(), ensure_ascii=False)


@mcp.resource("spectrumclaw://uav/live-state")
def uav_live_state() -> str:
    return json.dumps(get_uav_mission_service().inspect(), ensure_ascii=False)


@mcp.prompt("plan_safe_uav_mission")
def plan_safe_uav_mission() -> str:
    return (
        "将用户意图映射到固定任务模板；先调用 uav_get_state 和 uav_list_templates，"
        "再调用 uav_validate_plan。只在用户明确批准后调用 uav_execute_plan。"
        "不得生成原始坐标、速度、MAVLink 或真实飞行器控制。"
    )


def main() -> None:
    """Start the MCP adapter; stdio is the safe default transport."""
    transport = os.environ.get("SPECTRUMCLAW_UAV_MCP_TRANSPORT", "stdio").strip().lower()
    if transport not in {"stdio", "streamable-http", "sse"}:
        raise SystemExit("SPECTRUMCLAW_UAV_MCP_TRANSPORT 必须是 stdio、streamable-http 或 sse")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
