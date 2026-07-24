"""Typed, declarative contracts for safe UAV agent missions.

These models intentionally describe *what* approved simulator task is wanted,
never how PX4 should fly it.  Raw coordinates, MAVLink fields and velocity
values are rejected at schema parsing time.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MISSION_TEMPLATE_NAMES = (
    "takeoff_and_hover",
    "hover",
    "land",
    "return_to_launch",
    "inspect_safe_perimeter",
    "collect_camera_evidence",
    "search_safe_route",
)
MissionTemplate = Literal[*MISSION_TEMPLATE_NAMES]
SafeLandmark = Literal["north_gate", "south_gate", "east_gate", "west_gate"]


class MissionPlan(BaseModel):
    """A short-lived, reviewable request for one allowed simulator mission."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mission_id: str = Field(min_length=3, max_length=96)
    template: MissionTemplate
    landmark: SafeLandmark | None = None
    altitude_m: float | None = Field(default=None, ge=1.0, le=20.0)
    return_home: bool = True
    expires_at: float = Field(gt=0)


class PolicyDecision(BaseModel):
    """Public, structured result of the policy gate."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    code: str
    summary: str


def build_mission_plan(
    mission_id: str,
    template: str,
    landmark: str | None = None,
    altitude_m: float | None = None,
    expires_in_s: float = 120.0,
) -> MissionPlan:
    """Build the one declarative plan shape shared by native and MCP tools."""
    if not 5.0 <= float(expires_in_s) <= 600.0:
        raise ValueError("任务计划有效期必须在 5 到 600 秒之间")
    return MissionPlan(
        mission_id=mission_id,
        template=template,
        landmark=landmark,
        altitude_m=altitude_m,
        expires_at=time.time() + float(expires_in_s),
    )
