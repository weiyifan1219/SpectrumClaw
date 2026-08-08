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
            "counts": counts,
            "observed_mask": observed_mask,
            "sample_count": sum(sum(row) for row in counts),
            "observed_cells": observed_cells,
            "coverage_ratio": observed_cells / (self.rows * self.columns),
            "min_dbm": min(observed_values) if observed_values else None,
            "max_dbm": max(observed_values) if observed_values else None,
            "latest_timestamp": latest_timestamp or None,
        }
