from __future__ import annotations


def _route_cells(*, start, route, origin_m=(-20.0, -20.0), cell_size_m=4.0):
    from backend.skills.uav_spectrum_sim.route_planner import trace_coverage_cells

    cells = []
    current = start
    for waypoint in route:
        segment = list(trace_coverage_cells(
            current,
            waypoint,
            origin_m=origin_m,
            cell_size_m=cell_size_m,
        ))
        if cells and segment and cells[-1] == segment[0]:
            segment = segment[1:]
        cells.extend(segment)
        current = waypoint
    return cells


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


def test_astar_soft_revisit_penalty_prefers_fresh_measurement_cells():
    from backend.skills.uav_spectrum_sim.route_planner import (
        plan_obstacle_aware_route,
        trace_coverage_cells,
    )

    start = (-14.0, 1.0, 20.0)
    target = (14.0, 1.0, 20.0)
    origin = (-20.0, -20.0)
    visited_cells = set(trace_coverage_cells(
        (-8.0, 1.0, 20.0),
        (8.0, 1.0, 20.0),
        origin_m=origin,
        cell_size_m=4.0,
    ))

    route = plan_obstacle_aware_route(
        start=start,
        targets=(target,),
        objects=(),
        bounds_m=(-16.0, 16.0),
        resolution_m=2.0,
        visited_cells=visited_cells,
        coverage_origin_m=origin,
        coverage_cell_size_m=4.0,
        revisit_penalty_m=40.0,
    )
    crossed_cells = set(_route_cells(start=start, route=route, origin_m=origin))

    assert route[-1] == target
    assert len(route) > 1
    assert crossed_cells.isdisjoint(visited_cells)


def test_astar_soft_revisit_penalty_still_uses_an_old_cell_when_unavoidable():
    from backend.skills.uav_spectrum_sim.route_planner import (
        coverage_cell_key,
        plan_obstacle_aware_route,
    )

    start = (-6.0, 1.0, 20.0)
    target = (6.0, 1.0, 20.0)
    origin = (-8.0, -8.0)
    visited_cells = {
        coverage_cell_key((east, north), origin_m=origin, cell_size_m=4.0)
        for east in range(-8, 9, 2)
        for north in range(-8, 9, 2)
    }

    route = plan_obstacle_aware_route(
        start=start,
        targets=(target,),
        objects=(),
        bounds_m=(-8.0, 8.0),
        resolution_m=2.0,
        visited_cells=visited_cells,
        coverage_origin_m=origin,
        coverage_cell_size_m=4.0,
        revisit_penalty_m=40.0,
    )

    assert route[-1] == target
    assert set(_route_cells(start=start, route=route, origin_m=origin)).issubset(visited_cells)


def test_coverage_cell_keys_match_the_live_realtime_grid_contract():
    from backend.skills.uav_spectrum_sim.realtime_grid import RealtimeSpectrumGrid
    from backend.skills.uav_spectrum_sim.route_planner import coverage_cell_key

    grid = RealtimeSpectrumGrid(area_size_m=120.0, cell_size_m=4.0, layer_step_m=5.0)

    for point in ((-59.0, -59.0, 21.0), (-13.0, 14.0, 21.0), (0.0, 0.0, 21.0), (58.0, 58.0, 21.0)):
        layer, row, column = grid.cell_key(list(point))
        assert layer == 4
        assert coverage_cell_key(point) == (row, column)


def test_coverage_aware_astar_remains_collision_free_with_buildings():
    from backend.skills.uav_spectrum_sim.route_planner import (
        plan_obstacle_aware_route,
        route_is_collision_free,
        trace_coverage_cells,
    )

    building = {"id": "block", "position_m": [0.0, 0.0], "size_m": [8.0, 8.0, 18.0]}
    start = (0.0, -12.0, 20.0)
    target = (0.0, 12.0, 20.0)
    visited_cells = trace_coverage_cells((-10.0, -8.0, 20.0), (-10.0, 8.0, 20.0))

    route = plan_obstacle_aware_route(
        start=start,
        targets=(target,),
        objects=[building],
        bounds_m=(-20.0, 20.0),
        resolution_m=2.0,
        clearance_m=2.0,
        visited_cells=visited_cells,
        revisit_penalty_m=24.0,
    )

    assert route[-1] == target
    assert route_is_collision_free((start, *route), [building], clearance_m=2.0)
