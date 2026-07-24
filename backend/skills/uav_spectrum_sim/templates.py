"""Fixed mission-template catalog.

Templates turn a user-approved plan name into an existing constrained mission;
they never contain free coordinates, velocity values, or executable code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CompiledTemplate:
    mission: Literal["survey_safe_perimeter", "navigate_to_safe_landmark"]
    landmark: str | None
    requires_navigation: bool
    return_home: bool
    evidence: list[Literal["camera_frames", "lidar_summary"]]


def compile_template(template: str, *, landmark: str | None = None) -> CompiledTemplate:
    """Compile only named templates into the high-level mission adapter input."""
    if template == "inspect_safe_perimeter":
        return CompiledTemplate(
            mission="survey_safe_perimeter",
            landmark=None,
            requires_navigation=True,
            return_home=True,
            evidence=[],
        )
    if template == "collect_camera_evidence":
        if landmark not in {"north_gate", "south_gate", "east_gate", "west_gate"}:
            raise ValueError("采集画面任务必须选择预审安全地标")
        return CompiledTemplate(
            mission="navigate_to_safe_landmark",
            landmark=landmark,
            requires_navigation=True,
            return_home=True,
            evidence=["camera_frames"],
        )
    if template == "search_safe_route":
        return CompiledTemplate(
            mission="survey_safe_perimeter",
            landmark=None,
            requires_navigation=True,
            return_home=True,
            evidence=["lidar_summary"],
        )
    raise ValueError(f"不支持的固定任务模板：{template}")


def list_templates() -> list[dict[str, object]]:
    """Return the public catalog used by MCP clients and the future UI."""
    return [
        {
            "template": "inspect_safe_perimeter",
            "label": "安全周界巡检",
            "requires_landmark": False,
            "evidence": [],
        },
        {
            "template": "collect_camera_evidence",
            "label": "地标画面采集",
            "requires_landmark": True,
            "evidence": ["camera_frames"],
        },
        {
            "template": "search_safe_route",
            "label": "安全路线搜索",
            "requires_landmark": False,
            "evidence": ["lidar_summary"],
        },
    ]
