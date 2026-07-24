"""MCP-facing UAV contract tests that do not require a live PX4 process."""

from __future__ import annotations


def test_mcp_contract_exposes_only_plan_level_flight_tools():
    from backend.mcp.uav_contract import MCP_UAV_TOOL_NAMES, capability_document

    assert MCP_UAV_TOOL_NAMES == (
        "uav_get_state",
        "uav_list_templates",
        "uav_validate_plan",
        "uav_execute_plan",
        "uav_cancel_mission",
        "uav_get_run_events",
    )
    document = capability_document()
    assert "raw_mavlink" in document["not_exposed"]
    assert "arbitrary_velocity" in document["not_exposed"]
    assert document["scope"] == "px4_gazebo_simulation_only"


def test_native_registry_exposes_the_same_declarative_plan_schema():
    from backend.tools.registry import get_schema, register_all

    register_all()
    schema = get_schema("execute_uav_mission_plan")

    assert schema is not None
    props = schema["function"]["parameters"]["properties"]
    assert props["template"]["enum"] == [
        "takeoff_and_hover", "hover", "land", "return_to_launch",
        "inspect_safe_perimeter", "collect_camera_evidence", "search_safe_route",
    ]
    assert "target_enu_m" not in props
    assert "velocity_mps" not in props
