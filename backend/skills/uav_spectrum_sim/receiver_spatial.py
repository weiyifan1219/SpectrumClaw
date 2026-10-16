"""Sparse spatial evidence from modeled UAV receiver frames.

This layer is intentionally separate from Sionna path-gain REM samples: it
contains mixed, bandwidth-limited receiver RSSI measured from generated IQ.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from functools import lru_cache
from typing import Any

from .realtime_grid import RealtimeSpectrumGrid


MAX_CELLS = 2048
MAX_AGE_S = 3600


class ReceiverSpatialGrid:
    def __init__(self) -> None:
        self._geometry = RealtimeSpectrumGrid()
        self._cells: OrderedDict[tuple[int, int, int], dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def record(self, frame: dict[str, Any]) -> dict[str, Any] | None:
        """Aggregate frame RSSI in linear power at its measured ENU cell."""
        if not frame.get("current"):
            return None
        position = frame.get("position_m")
        if not isinstance(position, list) or len(position) != 3:
            return None
        key = self._geometry.cell_key(position)
        if key is None:
            return None
        value_dbm = float(frame.get("metrics", {}).get("rssi_dbm", float("nan")))
        timestamp = float(frame.get("generated_at") or time.time())
        if not math.isfinite(value_dbm) or not math.isfinite(timestamp):
            return None
        power_mw = 10 ** (value_dbm / 10)
        with self._lock:
            cell = self._cells.setdefault(key, {"sum_mw": 0.0, "count": 0})
            cell["sum_mw"] += power_mw
            cell["count"] += 1
            cell["position_m"] = [float(axis) for axis in position]
            cell["last_at"] = timestamp
            self._cells.move_to_end(key)
            while self._cells and (len(self._cells) > MAX_CELLS or next(iter(self._cells.values()))["last_at"] < timestamp - MAX_AGE_S):
                self._cells.popitem(last=False)
            result = dict(cell)
        layer, row, column = key
        return {
            "layer_index": layer, "row": row, "column": column,
            "position_m": result["position_m"],
            "rssi_dbm": round(10 * math.log10(result["sum_mw"] / result["count"]), 3),
            "frame_count": result["count"], "last_at": result["last_at"],
        }

    def snapshot(self, layer_index: int) -> dict[str, Any]:
        with self._lock:
            cells = [
                {"layer_index": layer, "row": row, "column": column,
                 "position_m": cell["position_m"],
                 "rssi_dbm": round(10 * math.log10(cell["sum_mw"] / cell["count"]), 3),
                 "frame_count": cell["count"], "last_at": cell["last_at"]}
                for (layer, row, column), cell in self._cells.items() if layer == layer_index
            ]
        return {
            "metric": "receiver_rssi_dbm", "source": "modeled_iq_receiver",
            "layer_index": layer_index, "shape": [self._geometry.rows, self._geometry.columns],
            "cell_size_m": self._geometry.cell_size_m,
            "observed_cells": len(cells), "samples": cells,
            "storage": "memory_only", "max_cells": MAX_CELLS, "max_age_s": MAX_AGE_S,
        }


@lru_cache(maxsize=1)
def get_receiver_spatial_grid() -> ReceiverSpatialGrid:
    return ReceiverSpatialGrid()
