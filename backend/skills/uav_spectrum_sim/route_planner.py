"""Deterministic obstacle-aware route planning for the bounded UAV sandbox."""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterable
from typing import Any


Point3 = tuple[float, float, float]
GridNode = tuple[int, int]
CoverageCell = tuple[int, int]


def _horizontal_point(point: tuple[float, ...]) -> tuple[float, float]:
    if len(point) < 2:
        raise ValueError("覆盖网格坐标至少需要 ENU 的 east/north 分量")
    east, north = float(point[0]), float(point[1])
    if not math.isfinite(east) or not math.isfinite(north):
        raise ValueError("覆盖网格坐标必须是有限数值")
    return east, north


def coverage_cell_key(
    point: tuple[float, ...],
    *,
    origin_m: tuple[float, float] = (-60.0, -60.0),
    cell_size_m: float = 4.0,
) -> CoverageCell:
    """Map an ENU point to the live grid's north-down ``(row, column)`` key."""
    east, north = _horizontal_point(point)
    size = float(cell_size_m)
    if size <= 0:
        raise ValueError("覆盖网格分辨率必须为正数")
    origin_east, origin_north = (float(value) for value in origin_m)
    columns = int(round((-2.0 * origin_east) / size))
    rows = int(round((-2.0 * origin_north) / size))
    if columns <= 0 or rows <= 0:
        raise ValueError("覆盖网格原点必须描述以 ENU 原点为中心的有限区域")
    column = int(math.floor((east - origin_east) / size))
    south_up_row = int(math.floor((north - origin_north) / size))
    return rows - 1 - south_up_row, column


def trace_coverage_cells(
    start: tuple[float, ...],
    end: tuple[float, ...],
    *,
    origin_m: tuple[float, float] = (-60.0, -60.0),
    cell_size_m: float = 4.0,
) -> tuple[CoverageCell, ...]:
    """Return every horizontal measurement cell crossed by a line segment."""
    start_xy = _horizontal_point(start)
    end_xy = _horizontal_point(end)
    size = float(cell_size_m)
    if size <= 0:
        raise ValueError("覆盖网格分辨率必须为正数")
    origin = tuple(float(value) for value in origin_m)
    breakpoints = {0.0, 1.0}

    def add_axis_boundaries(start_value: float, end_value: float, axis_origin: float) -> None:
        delta = end_value - start_value
        if abs(delta) < 1e-12:
            return
        lower, upper = sorted((start_value, end_value))
        first_index = math.floor((lower - axis_origin) / size) + 1
        boundary = axis_origin + first_index * size
        while boundary < upper - 1e-10:
            ratio = (boundary - start_value) / delta
            if 0.0 < ratio < 1.0:
                breakpoints.add(round(ratio, 12))
            boundary += size

    add_axis_boundaries(start_xy[0], end_xy[0], origin[0])
    add_axis_boundaries(start_xy[1], end_xy[1], origin[1])
    ordered = sorted(breakpoints)
    ratios = [0.0]
    ratios.extend((left + right) / 2.0 for left, right in zip(ordered, ordered[1:]))
    ratios.append(1.0)
    cells: list[CoverageCell] = []
    seen: set[CoverageCell] = set()
    for ratio in ratios:
        point = (
            start_xy[0] + (end_xy[0] - start_xy[0]) * ratio,
            start_xy[1] + (end_xy[1] - start_xy[1]) * ratio,
        )
        cell = coverage_cell_key(point, origin_m=origin, cell_size_m=size)
        if cell in seen:
            continue
        seen.add(cell)
        cells.append(cell)
    return tuple(cells)


def route_coverage_metrics(
    *,
    start: Point3,
    route: Iterable[Point3],
    prior_visited_cells: Iterable[CoverageCell] = (),
    origin_m: tuple[float, float] = (-60.0, -60.0),
    cell_size_m: float = 4.0,
) -> dict[str, float | int]:
    """Summarize distance and repeated measurement-cell entries for a route."""
    known_before = {tuple(cell) for cell in prior_visited_cells}
    seen = set(known_before)
    route_cells: set[CoverageCell] = set()
    revisited: set[CoverageCell] = set()
    visits = 0
    new_cells = 0
    revisit_steps = 0
    distance_m = 0.0
    previous_cell: CoverageCell | None = None
    current = tuple(float(value) for value in start)
    for waypoint in route:
        exact_waypoint = tuple(float(value) for value in waypoint)
        distance_m += math.dist(current[:2], exact_waypoint[:2])
        segment_cells = trace_coverage_cells(
            current,
            exact_waypoint,
            origin_m=origin_m,
            cell_size_m=cell_size_m,
        )
        for cell in segment_cells:
            if cell == previous_cell:
                continue
            is_initial_cell = visits == 0
            visits += 1
            route_cells.add(cell)
            if cell in seen:
                if not is_initial_cell:
                    revisit_steps += 1
                    revisited.add(cell)
            else:
                seen.add(cell)
                new_cells += 1
            previous_cell = cell
        current = exact_waypoint
    return {
        "cell_visits": visits,
        "unique_cells": len(route_cells),
        "new_cells": new_cells,
        "revisit_steps": revisit_steps,
        "revisited_cells": len(revisited),
        "revisit_ratio": round(revisit_steps / visits, 6) if visits else 0.0,
        "distance_m": round(distance_m, 3),
    }


def _building_rectangles(objects: Iterable[dict[str, Any]], clearance_m: float) -> list[tuple[float, float, float, float]]:
    rectangles: list[tuple[float, float, float, float]] = []
    for item in objects:
        if not isinstance(item, dict) or item.get("kind", "building") != "building":
            continue
        position = item.get("position_m")
        size = item.get("size_m")
        if not isinstance(position, (list, tuple)) or len(position) < 2:
            continue
        if not isinstance(size, (list, tuple)) or len(size) < 2:
            continue
        east, north = float(position[0]), float(position[1])
        half_width = float(size[0]) / 2.0 + clearance_m
        half_depth = float(size[1]) / 2.0 + clearance_m
        rectangles.append((east - half_width, east + half_width, north - half_depth, north + half_depth))
    return rectangles


def _point_blocked(point: tuple[float, float], rectangles: Iterable[tuple[float, float, float, float]]) -> bool:
    east, north = point
    return any(min_east <= east <= max_east and min_north <= north <= max_north
               for min_east, max_east, min_north, max_north in rectangles)


def _segment_hits_rectangle(
    start: tuple[float, float],
    end: tuple[float, float],
    rectangle: tuple[float, float, float, float],
) -> bool:
    """Return whether a closed segment intersects an inflated AABB."""
    min_east, max_east, min_north, max_north = rectangle
    delta_east = end[0] - start[0]
    delta_north = end[1] - start[1]
    t_min, t_max = 0.0, 1.0
    for origin, delta, lower, upper in (
        (start[0], delta_east, min_east, max_east),
        (start[1], delta_north, min_north, max_north),
    ):
        if abs(delta) < 1e-12:
            if origin < lower or origin > upper:
                return False
            continue
        entry = (lower - origin) / delta
        exit_ = (upper - origin) / delta
        if entry > exit_:
            entry, exit_ = exit_, entry
        t_min = max(t_min, entry)
        t_max = min(t_max, exit_)
        if t_min > t_max:
            return False
    return True


def _segment_clear(
    start: tuple[float, float],
    end: tuple[float, float],
    rectangles: Iterable[tuple[float, float, float, float]],
) -> bool:
    return not any(_segment_hits_rectangle(start, end, rectangle) for rectangle in rectangles)


def route_is_collision_free(
    route: Iterable[Point3],
    objects: Iterable[dict[str, Any]],
    *,
    clearance_m: float = 2.5,
) -> bool:
    """Validate every horizontal route segment against inflated buildings."""
    points = tuple(route)
    if len(points) < 2:
        return True
    rectangles = _building_rectangles(objects, max(0.0, float(clearance_m)))
    return all(
        _segment_clear((start[0], start[1]), (end[0], end[1]), rectangles)
        for start, end in zip(points, points[1:])
    )


def plan_obstacle_aware_route(
    *,
    start: Point3,
    targets: Iterable[Point3],
    objects: Iterable[dict[str, Any]],
    bounds_m: tuple[float, float] = (-35.0, 35.0),
    resolution_m: float = 2.0,
    clearance_m: float = 2.5,
    visited_cells: Iterable[CoverageCell] = (),
    coverage_origin_m: tuple[float, float] = (-60.0, -60.0),
    coverage_cell_size_m: float = 4.0,
    revisit_penalty_m: float = 0.0,
) -> tuple[Point3, ...]:
    """Plan a collision-free route with coverage-aware A*.

    The returned tuple excludes ``start`` and retains each requested target
    exactly. Buildings are inflated by the requested clearance before search,
    so the route remains usable despite small PX4 tracking errors. Previously
    visited measurement cells add a finite cost rather than becoming blocked;
    safety corridors and return paths therefore remain reachable. This is the
    deterministic transit/safety layer: an autonomous agent's target selector
    must still omit already measured candidate targets before calling it.
    """
    lower, upper = (float(value) for value in bounds_m)
    resolution = float(resolution_m)
    if resolution <= 0 or lower >= upper:
        raise ValueError("A* 路径规划的边界或网格分辨率无效")
    coverage_size = float(coverage_cell_size_m)
    revisit_penalty = float(revisit_penalty_m)
    if coverage_size <= 0 or revisit_penalty < 0:
        raise ValueError("覆盖网格分辨率必须为正数，重复访问惩罚不能为负数")
    known_visited: set[CoverageCell] = {
        (int(cell[0]), int(cell[1]))
        for cell in visited_cells
    }
    rectangles = _building_rectangles(objects, max(0.0, float(clearance_m)))
    node_count = int(math.floor((upper - lower) / resolution)) + 1

    def to_point(node: GridNode) -> tuple[float, float]:
        return lower + node[0] * resolution, lower + node[1] * resolution

    def nearest_free_node(point: tuple[float, float]) -> GridNode:
        base = (
            min(node_count - 1, max(0, int(round((point[0] - lower) / resolution)))),
            min(node_count - 1, max(0, int(round((point[1] - lower) / resolution)))),
        )
        candidates = (
            (math.hypot(i - base[0], j - base[1]), (i, j))
            for i in range(node_count)
            for j in range(node_count)
            if not _point_blocked(to_point((i, j)), rectangles)
        )
        try:
            return min(candidates, key=lambda item: item[0])[1]
        except ValueError as exc:
            raise RuntimeError("规划区域被障碍物完全占据") from exc

    directions = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))

    def crossed_cells(start_point: tuple[float, float], end_point: tuple[float, float]) -> tuple[CoverageCell, ...]:
        return trace_coverage_cells(
            start_point,
            end_point,
            origin_m=coverage_origin_m,
            cell_size_m=coverage_size,
        )

    def polyline_revisit_count(points: list[tuple[float, float]]) -> int:
        cells: list[CoverageCell] = []
        for segment_start, segment_end in zip(points, points[1:]):
            segment_cells = list(crossed_cells(segment_start, segment_end))
            if cells and segment_cells and cells[-1] == segment_cells[0]:
                segment_cells = segment_cells[1:]
            cells.extend(segment_cells)
        if cells:
            cells = cells[1:]  # The current cell is not a repeated flight decision.
        return sum(cell in known_visited for cell in cells)

    def astar(start_point: tuple[float, float], goal_point: tuple[float, float]) -> list[tuple[float, float]]:
        direct_revisits = polyline_revisit_count([start_point, goal_point])
        if _segment_clear(start_point, goal_point, rectangles) and (
            revisit_penalty <= 0 or direct_revisits == 0
        ):
            return [goal_point]
        start_node = nearest_free_node(start_point)
        goal_node = nearest_free_node(goal_point)
        queue: list[tuple[float, float, GridNode]] = [(0.0, 0.0, start_node)]
        came_from: dict[GridNode, GridNode] = {}
        costs: dict[GridNode, float] = {start_node: 0.0}
        visited: set[GridNode] = set()
        while queue:
            _priority, current_cost, current = heapq.heappop(queue)
            if current in visited:
                continue
            visited.add(current)
            if current == goal_node:
                break
            for delta_i, delta_j in directions:
                neighbor = current[0] + delta_i, current[1] + delta_j
                if not (0 <= neighbor[0] < node_count and 0 <= neighbor[1] < node_count):
                    continue
                current_xy, neighbor_xy = to_point(current), to_point(neighbor)
                if _point_blocked(neighbor_xy, rectangles) or not _segment_clear(current_xy, neighbor_xy, rectangles):
                    continue
                step_cost = resolution * (math.sqrt(2.0) if delta_i and delta_j else 1.0)
                step_cells = crossed_cells(current_xy, neighbor_xy)
                step_cost += revisit_penalty * sum(
                    cell in known_visited
                    for cell in step_cells[1:]
                )
                next_cost = current_cost + step_cost
                if next_cost >= costs.get(neighbor, math.inf):
                    continue
                costs[neighbor] = next_cost
                came_from[neighbor] = current
                heuristic = math.hypot(neighbor[0] - goal_node[0], neighbor[1] - goal_node[1]) * resolution
                heapq.heappush(queue, (next_cost + heuristic, next_cost, neighbor))
        if goal_node not in costs:
            raise RuntimeError("A* 未找到满足安全间隔的航线")
        nodes = [goal_node]
        while nodes[-1] != start_node:
            nodes.append(came_from[nodes[-1]])
        nodes.reverse()
        raw = [start_point, *(to_point(node) for node in nodes[1:]), goal_point]
        compressed = [raw[0]]
        anchor = 0
        while anchor < len(raw) - 1:
            candidate = len(raw) - 1
            while candidate > anchor + 1:
                direct_clear = _segment_clear(raw[anchor], raw[candidate], rectangles)
                does_not_add_revisits = (
                    revisit_penalty <= 0
                    or polyline_revisit_count([raw[anchor], raw[candidate]])
                    <= polyline_revisit_count(raw[anchor:candidate + 1])
                )
                if direct_clear and does_not_add_revisits:
                    break
                candidate -= 1
            compressed.append(raw[candidate])
            anchor = candidate
        return compressed[1:]

    planned: list[Point3] = []
    current = (float(start[0]), float(start[1]), float(start[2]))
    for target in targets:
        exact_target = (float(target[0]), float(target[1]), float(target[2]))
        segment = astar((current[0], current[1]), (exact_target[0], exact_target[1]))
        segment_3d = [(east, north, exact_target[2]) for east, north in segment]
        planned.extend(segment_3d)
        segment_start: Point3 = current
        for waypoint in segment_3d:
            known_visited.update(trace_coverage_cells(
                segment_start,
                waypoint,
                origin_m=coverage_origin_m,
                cell_size_m=coverage_size,
            ))
            segment_start = waypoint
        current = exact_target
    result = tuple(planned)
    if not route_is_collision_free((start, *result), objects, clearance_m=clearance_m):
        raise RuntimeError("规划结果未通过碰撞校验")
    return result
