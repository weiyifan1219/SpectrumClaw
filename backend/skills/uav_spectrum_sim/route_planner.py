"""Deterministic obstacle-aware route planning for the bounded UAV sandbox."""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterable
from typing import Any


Point3 = tuple[float, float, float]
GridNode = tuple[int, int]


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
) -> tuple[Point3, ...]:
    """Plan a collision-free route with A* and line-of-sight compression.

    The returned tuple excludes ``start`` and retains each requested target
    exactly. Buildings are inflated by the requested clearance before search,
    so the route remains usable despite small PX4 tracking errors.
    """
    lower, upper = (float(value) for value in bounds_m)
    resolution = float(resolution_m)
    if resolution <= 0 or lower >= upper:
        raise ValueError("A* 路径规划的边界或网格分辨率无效")
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

    def astar(start_point: tuple[float, float], goal_point: tuple[float, float]) -> list[tuple[float, float]]:
        if _segment_clear(start_point, goal_point, rectangles):
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
            while candidate > anchor + 1 and not _segment_clear(raw[anchor], raw[candidate], rectangles):
                candidate -= 1
            compressed.append(raw[candidate])
            anchor = candidate
        return compressed[1:]

    planned: list[Point3] = []
    current = (float(start[0]), float(start[1]), float(start[2]))
    for target in targets:
        exact_target = (float(target[0]), float(target[1]), float(target[2]))
        segment = astar((current[0], current[1]), (exact_target[0], exact_target[1]))
        planned.extend((east, north, exact_target[2]) for east, north in segment)
        current = exact_target
    result = tuple(planned)
    if not route_is_collision_free((start, *result), objects, clearance_m=clearance_m):
        raise RuntimeError("规划结果未通过碰撞校验")
    return result
