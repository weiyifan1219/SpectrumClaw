"""The built-in agent must use the same high-level adapter as MCP."""

from __future__ import annotations


def test_uav_agent_intent_exposes_only_task_level_tools():
    from backend.agent.runtime import _tool_names_for_intent

    assert _tool_names_for_intent("uav") == [
        "get_uav_mission_status",
        "execute_uav_mission",
        "cancel_uav_mission",
    ]


def test_uav_task_schemas_are_registered():
    from backend.tools.registry import get_schema, register_all

    register_all()
    schema = get_schema("execute_uav_mission")

    assert schema is not None
    assert schema["function"]["parameters"]["properties"]["mission"]["enum"] == [
        "takeoff_and_hover", "hover", "land", "return_to_launch",
        "navigate_to_safe_landmark", "survey_safe_perimeter",
    ]
    assert schema["function"]["parameters"]["properties"]["landmark"]["enum"] == [
        "north_gate", "south_gate", "east_gate", "west_gate"
    ]
