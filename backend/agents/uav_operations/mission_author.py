"""Constrained mission-author subagent.

The first version intentionally has no shell, network or flight capability.
It converts a small, auditable Chinese intent surface into ``MissionPlan``.
"""

from __future__ import annotations

import time

from ...skills.uav_spectrum_sim.contracts import MissionPlan
from ...skills.uav_spectrum_sim.templates import compile_template
from .sandbox import MissionSandbox


LANDMARK_ALIASES = {
    "北门": "north_gate",
    "南门": "south_gate",
    "东门": "east_gate",
    "西门": "west_gate",
    "north_gate": "north_gate",
    "south_gate": "south_gate",
    "east_gate": "east_gate",
    "west_gate": "west_gate",
}


class MissionAuthor:
    def __init__(self, sandbox: MissionSandbox, *, plan_ttl_s: float = 120.0) -> None:
        self._sandbox = sandbox
        self._plan_ttl_s = plan_ttl_s

    @staticmethod
    def _template_for(intent: str) -> str:
        text = intent.lower()
        if any(word in text for word in ("坐标", "mavlink", "速度", "m/s", "shell", "脚本执行")):
            raise ValueError("无法映射含原始飞控参数的请求")
        if any(word in text for word in ("巡检", "周界", "巡逻")):
            return "inspect_safe_perimeter"
        if any(word in text for word in ("拍照", "拍摄", "画面", "采集")):
            return "collect_camera_evidence"
        if any(word in text for word in ("搜寻", "搜索", "搜索路线")):
            return "search_safe_route"
        if "返航" in text:
            return "return_to_launch"
        if "降落" in text:
            return "land"
        if "起飞" in text:
            return "takeoff_and_hover"
        if "悬停" in text:
            return "hover"
        raise ValueError("无法映射到固定安全任务模板")

    @staticmethod
    def _landmark_for(intent: str) -> str | None:
        text = intent.lower()
        return next((value for alias, value in LANDMARK_ALIASES.items() if alias in text), None)

    def author(self, run_id: str, intent: str) -> MissionPlan:
        template = self._template_for(intent)
        landmark = self._landmark_for(intent)
        return self.plan_for(run_id, template, landmark)

    def plan_for(self, run_id: str, template: str, landmark: str | None) -> MissionPlan:
        if template == "collect_camera_evidence" and landmark is None:
            raise ValueError("采集画面任务需要指定北门、南门、东门或西门")
        plan = MissionPlan(
            mission_id=run_id,
            template=template,
            landmark=landmark,
            expires_at=time.time() + self._plan_ttl_s,
        )
        self._sandbox.write_json(run_id, "mission_plan.json", plan.model_dump())
        compiled = compile_template(template, landmark=landmark) if template not in {
            "takeoff_and_hover", "hover", "land", "return_to_launch",
        } else None
        self._sandbox.write_json(run_id, "mission_program.json", {
            "language": "spectrumclaw-uav-dsl/v1",
            "template": template,
            "steps": [{"op": compiled.mission if compiled else template}],
            "landmark": landmark,
            "return_home": plan.return_home,
        })
        return plan
