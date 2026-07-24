"""Shared public contract for native and MCP UAV task entry points."""

from __future__ import annotations

from typing import Any

from ..skills.uav_spectrum_sim.contracts import MISSION_TEMPLATE_NAMES
from ..skills.uav_spectrum_sim.templates import list_templates


MCP_UAV_TOOL_NAMES = (
    "uav_get_state",
    "uav_list_templates",
    "uav_validate_plan",
    "uav_execute_plan",
    "uav_cancel_mission",
    "uav_get_run_events",
)


def capability_document() -> dict[str, Any]:
    """Machine-readable safety contract returned by the MCP resource."""
    return {
        "scope": "px4_gazebo_simulation_only",
        "tools": list(MCP_UAV_TOOL_NAMES),
        "templates": list(MISSION_TEMPLATE_NAMES),
        "template_catalog": list_templates(),
        "manual_control": "browser manual control has priority and preempts missions",
        "not_exposed": [
            "raw_mavlink",
            "arbitrary_shell",
            "arbitrary_velocity",
            "raw_coordinates",
            "real_vehicle_control",
        ],
    }
