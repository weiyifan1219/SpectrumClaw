"""Safety gate for declarative UAV simulator mission plans."""

from __future__ import annotations

import time
from typing import Any

from .contracts import MissionPlan, PolicyDecision


class MissionPolicy:
    """Validate a plan against current simulator state before any action."""

    def validate(self, plan: MissionPlan, runtime_status: dict[str, Any]) -> PolicyDecision:
        runtime = runtime_status.get("runtime", {}) if isinstance(runtime_status, dict) else {}
        if runtime.get("state") != "running":
            return PolicyDecision(allowed=False, code="simulator_not_running", summary="PX4/Gazebo 仿真未运行。")
        if bool(runtime.get("manual", {}).get("enabled")):
            return PolicyDecision(allowed=False, code="manual_control_active", summary="网页 WASD 正在接管飞行器。")
        if plan.expires_at <= time.time():
            return PolicyDecision(allowed=False, code="plan_expired", summary="任务计划已过期，需要重新生成。")
        if plan.template == "collect_camera_evidence" and plan.landmark is None:
            return PolicyDecision(allowed=False, code="landmark_required", summary="采集画面任务必须选择预审安全地标。")
        if plan.template in {"inspect_safe_perimeter", "search_safe_route"}:
            navigation = runtime.get("agent_navigation", {})
            if isinstance(navigation, dict) and not navigation.get("ready", False):
                return PolicyDecision(allowed=False, code="agent_navigation_bridge_not_ready", summary="智能体导航桥尚未就绪。")
        return PolicyDecision(allowed=True, code="allowed", summary="任务满足当前仿真安全策略，可等待用户批准。")
