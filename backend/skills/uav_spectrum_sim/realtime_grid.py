"""Thread-safe sparse radio-environment grid built from live UAV samples."""

from __future__ import annotations

import math
import threading
from typing import Any


class RealtimeSpectrumGrid:
    """Accumulate measured RF power without filling unobserved cells.

    Coordinates use the same local ENU frame as Gazebo and Sionna.  Each layer
    is a vertical bin; rows are stored north-to-south so the returned matrix is
    directly displayable as a top-down heatmap.
    """

    def __init__(
        self,
        *,
        area_size_m: float = 120.0,
        cell_size_m: float = 4.0,
        layer_step_m: float = 5.0,
    ) -> None:
        if area_size_m <= 0 or cell_size_m <= 0 or layer_step_m <= 0:
            raise ValueError("网格尺寸和高度层间隔必须为正数")
        cells_per_axis = int(round(area_size_m / cell_size_m))
        if cells_per_axis < 1 or not math.isclose(cells_per_axis * cell_size_m, area_size_m, abs_tol=1e-6):
            raise ValueError("区域边长必须能被单元格边长整除")
        self.area_size_m = float(area_size_m)
        self.cell_size_m = float(cell_size_m)
        self.layer_step_m = float(layer_step_m)
        self.rows = cells_per_axis
        self.columns = cells_per_axis
        self.min_east_m = -self.area_size_m / 2
        self.max_east_m = self.area_size_m / 2
        self.min_north_m = -self.area_size_m / 2
        self.max_north_m = self.area_size_m / 2
        self._layers: dict[int, dict[tuple[int, int], dict[str, Any]]] = {}
        self._layer_sample_counts: dict[int, int] = {}
        self._transmitters: set[str] = set()
        self._lock = threading.Lock()

    def clear_layer(self, layer_index: int) -> None:
        """Discard samples from one height layer before a new survey campaign."""
        selected_layer = max(0, int(layer_index))
        with self._lock:
            self._layers.pop(selected_layer, None)
            self._layer_sample_counts.pop(selected_layer, None)

    @staticmethod
    def _power_mw(dbm: float) -> float:
        return 10.0 ** (float(dbm) / 10.0)

    @staticmethod
    def _dbm(power_mw: float) -> float:
        return 10.0 * math.log10(max(float(power_mw), 1e-30))

    def _indices(self, position_m: list[float]) -> tuple[int, int, int] | None:
        east, north, height = (float(value) for value in position_m)
        if not all(math.isfinite(value) for value in (east, north, height)):
            return None
        if not (self.min_east_m <= east < self.max_east_m and self.min_north_m <= north < self.max_north_m):
            return None
        column = int(math.floor((east - self.min_east_m) / self.cell_size_m))
        south_up_row = int(math.floor((north - self.min_north_m) / self.cell_size_m))
        row = self.rows - 1 - south_up_row
        layer_index = max(0, int(math.floor(max(0.0, height) / self.layer_step_m)))
        return layer_index, row, column

    def cell_key(self, position_m: list[float]) -> tuple[int, int, int] | None:
        """Expose the stable layer/row/column identity used by the RT queue."""
        return self._indices(position_m)

    def trace_positions(self, start_m: list[float], end_m: list[float]) -> list[dict[str, Any]]:
        """Return one representative pose for every grid cell a segment crosses.

        Telemetry can move farther than one cell between two browser/backend
        ticks. A grid-space DDA keeps those intermediate cells instead of
        silently dropping them while the RT worker is busy.
        """
        start_indices = self._indices(start_m)
        end_indices = self._indices(end_m)
        if start_indices is None or end_indices is None:
            return []
        breakpoints = {0.0, 1.0}

        def add_axis_boundaries(start: float, end: float, origin: float, step: float) -> None:
            delta = end - start
            if abs(delta) < 1e-12:
                return
            lower, upper = sorted((start, end))
            first_index = math.floor((lower - origin) / step) + 1
            boundary = origin + first_index * step
            while boundary < upper - 1e-10:
                ratio = (boundary - start) / delta
                if 0.0 < ratio < 1.0:
                    breakpoints.add(round(ratio, 12))
                boundary += step

        add_axis_boundaries(float(start_m[0]), float(end_m[0]), self.min_east_m, self.cell_size_m)
        add_axis_boundaries(float(start_m[1]), float(end_m[1]), self.min_north_m, self.cell_size_m)
        add_axis_boundaries(float(start_m[2]), float(end_m[2]), 0.0, self.layer_step_m)
        ordered = sorted(breakpoints)
        ratios = [0.0]
        ratios.extend((left + right) / 2.0 for left, right in zip(ordered, ordered[1:]))
        ratios.append(1.0)
        traced: list[dict[str, Any]] = []
        seen: set[tuple[int, int, int]] = set()
        for ratio in ratios:
            position = [
                float(start_m[axis]) + (float(end_m[axis]) - float(start_m[axis])) * ratio
                for axis in range(3)
            ]
            cell = self._indices(position)
            if cell is None or cell in seen:
                continue
            seen.add(cell)
            layer_index, row, column = cell
            traced.append({
                "layer_index": layer_index,
                "row": row,
                "column": column,
                "position_m": position,
            })
        if traced and end_indices in seen:
            traced[-1]["position_m"] = [float(value) for value in end_m]
        if traced:
            traced[0]["position_m"] = [float(value) for value in start_m]
        return traced

    def record(self, observation: dict[str, Any]) -> dict[str, Any]:
        position = observation.get("position_m") if isinstance(observation, dict) else None
        if not isinstance(position, list) or len(position) != 3:
            raise ValueError("实时频谱观测缺少三维 ENU 位姿")
        indices = self._indices(position)
        if indices is None:
            raise ValueError("无人机位姿超出实时频谱网格范围")
        anchors = observation.get("anchors")
        if not isinstance(anchors, list):
            raise ValueError("实时频谱观测缺少发射源功率")
        powers: dict[str, float] = {}
        for anchor in anchors:
            if not isinstance(anchor, dict) or not isinstance(anchor.get("id"), str):
                continue
            try:
                value = float(anchor["received_power_dbm"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(value):
                powers[anchor["id"]] = self._power_mw(value)
        if not powers:
            raise ValueError("实时频谱观测没有有效的接收功率")
        powers["all"] = sum(powers.values())
        layer_index, row, column = indices
        timestamp = float(observation.get("timestamp") or 0.0)
        with self._lock:
            layer = self._layers.setdefault(layer_index, {})
            cell = layer.setdefault((row, column), {"metrics": {}, "last_timestamp": 0.0, "last_position_m": None})
            for transmitter_id, power_mw in powers.items():
                metric = cell["metrics"].setdefault(transmitter_id, {"sum_mw": 0.0, "count": 0})
                metric["sum_mw"] += power_mw
                metric["count"] += 1
            cell["last_timestamp"] = timestamp
            cell["last_position_m"] = [float(value) for value in position]
            self._layer_sample_counts[layer_index] = self._layer_sample_counts.get(layer_index, 0) + 1
            self._transmitters.update(key for key in powers if key != "all")
            cell_values_dbm = {
                key: round(self._dbm(metric["sum_mw"] / metric["count"]), 4)
                for key, metric in cell["metrics"].items()
            }
            cell_counts = {key: int(metric["count"]) for key, metric in cell["metrics"].items()}
        return {
            "layer_index": layer_index,
            "row": row,
            "column": column,
            "height_range_m": [layer_index * self.layer_step_m, (layer_index + 1) * self.layer_step_m],
            "position_m": [float(value) for value in position],
            "timestamp": timestamp,
            "values_dbm": cell_values_dbm,
            "counts": cell_counts,
        }

    def snapshot(self, *, layer_index: int, transmitter_id: str = "all") -> dict[str, Any]:
        selected_layer = max(0, int(layer_index))
        selected_tx = str(transmitter_id or "all")
        values: list[list[float | None]] = [[None for _ in range(self.columns)] for _ in range(self.rows)]
        counts: list[list[int]] = [[0 for _ in range(self.columns)] for _ in range(self.rows)]
        observed_mask: list[list[int]] = [[0 for _ in range(self.columns)] for _ in range(self.rows)]
        latest_timestamp = 0.0
        with self._lock:
            cells = list(self._layers.get(selected_layer, {}).items())
            available_transmitters = sorted(self._transmitters)
        def matrix_for(transmitter: str) -> list[list[float | None]]:
            matrix: list[list[float | None]] = [[None for _ in range(self.columns)] for _ in range(self.rows)]
            for (cell_row, cell_column), cell in cells:
                metric = cell["metrics"].get(transmitter)
                if metric and metric["count"] > 0:
                    matrix[cell_row][cell_column] = round(self._dbm(metric["sum_mw"] / metric["count"]), 4)
            return matrix

        for (row, column), cell in cells:
            metric = cell["metrics"].get(selected_tx)
            if not metric or metric["count"] <= 0:
                continue
            values[row][column] = round(self._dbm(metric["sum_mw"] / metric["count"]), 4)
            counts[row][column] = int(metric["count"])
            observed_mask[row][column] = 1
            latest_timestamp = max(latest_timestamp, float(cell.get("last_timestamp") or 0.0))
        observed_values = [value for row in values for value in row if value is not None]
        observed_cells = len(observed_values)
        reconstructed_values: list[list[float]] | None = None
        estimated_sources: dict[str, dict[str, Any]] = {}
        if observed_cells >= 3:
            if selected_tx == "all":
                layer_transmitters = [
                    transmitter
                    for transmitter in available_transmitters
                    if sum(value is not None for row in matrix_for(transmitter) for value in row) >= 3
                ]
                reconstructed_sources = []
                for transmitter in layer_transmitters:
                    source_matrix, source_model = self._blind_path_loss_idw_reconstruct(
                        matrix_for(transmitter),
                        layer_index=selected_layer,
                    )
                    reconstructed_sources.append(source_matrix)
                    estimated_sources[transmitter] = source_model
                if reconstructed_sources:
                    reconstructed_values = [
                        [
                            round(self._dbm(sum(self._power_mw(source[row][column]) for source in reconstructed_sources)), 4)
                            for column in range(self.columns)
                        ]
                        for row in range(self.rows)
                    ]
                    # Total-power measurements remain ground truth rather than
                    # being replaced by the fitted propagation surface.
                    for row in range(self.rows):
                        for column in range(self.columns):
                            if values[row][column] is not None:
                                reconstructed_values[row][column] = float(values[row][column])
            else:
                reconstructed_values, source_model = self._blind_path_loss_idw_reconstruct(
                    values,
                    layer_index=selected_layer,
                )
                estimated_sources[selected_tx] = source_model
        total_cells = self.rows * self.columns
        reconstruction = {
            "method": "blind_path_loss_idw",
            "ready": reconstructed_values is not None,
            "minimum_observed_cells": 3,
            "source_cells": observed_cells,
            "estimated_cells": total_cells - observed_cells if reconstructed_values is not None else 0,
            "coverage_ratio": 1.0 if reconstructed_values is not None else observed_cells / total_cells,
            "power": 2.0,
            "max_neighbors": 8,
            "prior": "rss_inferred_source",
            "estimated_sources": estimated_sources,
        }
        return {
            "frame": "local-ENU",
            "metric": "total_rf_power_dbm" if selected_tx == "all" else "received_power_dbm",
            "transmitter_id": selected_tx,
            "available_transmitters": available_transmitters,
            "layer_index": selected_layer,
            "height_range_m": [selected_layer * self.layer_step_m, (selected_layer + 1) * self.layer_step_m],
            "layer_step_m": self.layer_step_m,
            "bounds_m": [self.min_east_m, self.max_east_m, self.min_north_m, self.max_north_m],
            "cell_size_m": self.cell_size_m,
            "shape": [self.rows, self.columns],
            "values_dbm": values,
            "reconstructed_values_dbm": reconstructed_values,
            "counts": counts,
            "observed_mask": observed_mask,
            "sample_count": sum(sum(row) for row in counts),
            "observed_cells": observed_cells,
            "coverage_ratio": observed_cells / (self.rows * self.columns),
            "min_dbm": min(observed_values) if observed_values else None,
            "max_dbm": max(observed_values) if observed_values else None,
            "latest_timestamp": latest_timestamp or None,
            "reconstruction": reconstruction,
        }

    def _cell_position(self, row: int, column: int, layer_index: int) -> tuple[float, float, float]:
        return (
            self.min_east_m + (column + 0.5) * self.cell_size_m,
            self.max_north_m - (row + 0.5) * self.cell_size_m,
            (layer_index + 0.5) * self.layer_step_m,
        )

    def _blind_path_loss_idw_reconstruct(
        self,
        values: list[list[float | None]],
        *,
        layer_index: int,
    ) -> tuple[list[list[float]], dict[str, Any]]:
        """Infer an unknown source from RSS, then interpolate model residuals.

        Pure IDW tends to flatten sparse measurements into a nearly uniform
        sheet. This blind fit searches candidate grid cells using only measured
        RSS and jointly estimates reference power and path-loss exponent. No
        declared transmitter coordinate enters the reconstruction. Residual
        IDW then retains scene-specific deviations and exact measured cells.
        """
        samples = [
            (row, column, float(value))
            for row, values_row in enumerate(values)
            for column, value in enumerate(values_row)
            if value is not None
        ]
        sample_positions = [self._cell_position(row, column, layer_index) for row, column, _value in samples]
        ys = [value for _row, _column, value in samples]
        strongest_dbm = max(ys)
        strong_samples = sorted(
            zip(sample_positions, ys),
            key=lambda item: item[1],
            reverse=True,
        )[:max(2, math.ceil(len(samples) * 0.3))]
        strong_weights = [10.0 ** ((power - strongest_dbm) / 10.0) for _point, power in strong_samples]
        weight_total = sum(strong_weights)
        strong_centroid = (
            sum(point[0] * weight for (point, _power), weight in zip(strong_samples, strong_weights)) / weight_total,
            sum(point[1] * weight for (point, _power), weight in zip(strong_samples, strong_weights)) / weight_total,
        )
        minimum_distance = max(1.0, self.cell_size_m / 2.0)

        def candidate_fit(source_east: float, source_north: float) -> tuple[float, float, float]:
            xs = [
                math.log10(max(minimum_distance, math.hypot(point[0] - source_east, point[1] - source_north)))
                for point in sample_positions
            ]
            mean_x = sum(xs) / len(xs)
            mean_y = sum(ys) / len(ys)
            variance = sum((value - mean_x) ** 2 for value in xs)
            slope = (
                sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / variance
                if variance > 1e-9 else -20.0
            )
            slope = min(-10.0, max(-60.0, slope))
            intercept = mean_y - slope * mean_x
            squared_errors = sorted((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
            retained = squared_errors[:max(3, math.ceil(len(squared_errors) * 0.85))]
            robust_rmse = math.sqrt(sum(retained) / len(retained))
            centroid_penalty = 0.035 * math.hypot(
                source_east - strong_centroid[0],
                source_north - strong_centroid[1],
            ) / self.cell_size_m
            return robust_rmse + centroid_penalty, slope, intercept

        best: tuple[float, float, float, float, float] | None = None
        for candidate_row in range(self.rows):
            for candidate_column in range(self.columns):
                source_east, source_north, _source_height = self._cell_position(
                    candidate_row, candidate_column, layer_index,
                )
                score, slope, intercept = candidate_fit(source_east, source_north)
                candidate = (score, source_east, source_north, slope, intercept)
                if best is None or candidate < best:
                    best = candidate
        assert best is not None
        score, source_east, source_north, slope, intercept = best
        transmitter = (source_east, source_north)

        def log_distance(row: int, column: int) -> float:
            point = self._cell_position(row, column, layer_index)
            distance = math.hypot(point[0] - transmitter[0], point[1] - transmitter[1])
            return math.log10(max(distance, minimum_distance))

        residual_samples = [
            (row, column, value - (intercept + slope * log_distance(row, column)))
            for row, column, value in samples
        ]
        observed_min, observed_max = min(ys), max(ys)
        reconstructed: list[list[float]] = []
        for row in range(self.rows):
            reconstructed_row: list[float] = []
            for column in range(self.columns):
                measured = values[row][column]
                if measured is not None:
                    reconstructed_row.append(float(measured))
                    continue
                neighbors = sorted(
                    residual_samples,
                    key=lambda sample: (sample[0] - row) ** 2 + (sample[1] - column) ** 2,
                )[:8]
                weighted_sum = 0.0
                weight_total = 0.0
                for sample_row, sample_column, sample_residual in neighbors:
                    distance_m = self.cell_size_m * math.hypot(sample_row - row, sample_column - column)
                    weight = 1.0 / max(distance_m, 1e-6) ** 2.0
                    weighted_sum += weight * sample_residual
                    weight_total += weight
                prior = intercept + slope * log_distance(row, column)
                residual = weighted_sum / weight_total
                estimate = prior + max(-8.0, min(8.0, residual))
                estimate = max(observed_min - 15.0, min(observed_max + 15.0, estimate))
                reconstructed_row.append(round(estimate, 4))
            reconstructed.append(reconstructed_row)
        model_rmse = math.sqrt(sum(residual ** 2 for _row, _column, residual in residual_samples) / len(residual_samples))
        model = {
            "position_m": [round(value, 4) for value in transmitter],
            "position_basis": "rss_grid_search",
            "altitude_m": None,
            "height_basis": "selected_layer_only",
            "height_range_m": [layer_index * self.layer_step_m, (layer_index + 1) * self.layer_step_m],
            "reference_power_dbm": round(intercept, 4),
            "path_loss_exponent": round(-slope / 10.0, 4),
            "rmse_db": round(model_rmse, 4),
            "confidence": round(1.0 / (1.0 + max(score, 0.0)), 4),
            "sample_count": len(samples),
        }
        return reconstructed, model
