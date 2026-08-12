from __future__ import annotations


def test_astar_route_detours_around_an_inflated_building_footprint():
    from backend.skills.uav_spectrum_sim.route_planner import (
        plan_obstacle_aware_route,
        route_is_collision_free,
    )

    building = {"id": "block", "position_m": [0.0, 0.0], "size_m": [8.0, 8.0, 18.0]}
    start = (0.0, -12.0, 20.0)
    target = (0.0, 12.0, 20.0)

    route = plan_obstacle_aware_route(
        start=start,
        targets=(target,),
        objects=[building],
        bounds_m=(-20.0, 20.0),
        resolution_m=2.0,
        clearance_m=2.0,
    )

    assert route[-1] == target
    assert len(route) > 1
    assert route_is_collision_free((start, *route), [building], clearance_m=2.0)


def test_uav_mission_service_uses_the_planned_collision_free_survey_route():
    from backend.skills.uav_spectrum_sim.mission import UavMissionService

    route = ((-4.0, -8.0, 20.0), (4.0, 0.0, 20.0), (0.0, 8.0, 20.0))
    navigation_targets = []
    service = UavMissionService(
        status_reader=lambda: {
            "runtime": {
                "state": "running",
                "manual": {"enabled": False},
                "agent_navigation": {"ready": True},
                "camera": {"vehicle": {"position_m": [0.0, 0.0, 20.0]}},
            },
        },
        command_executor=lambda *_args: {"ok": True},
        navigation_writer=lambda target: navigation_targets.append(target) or {"ok": True},
        navigation_clearer=lambda: {"ok": True},
        safe_perimeter_route=route,
    )
    service._takeoff_to_cruise = lambda _mission: None
    service._wait_for_position = lambda _target, _on_progress=None: "arrived"

    result = service.execute("survey_safe_perimeter")

    assert result["ok"] is True
    assert navigation_targets == [list(target) for target in route]
