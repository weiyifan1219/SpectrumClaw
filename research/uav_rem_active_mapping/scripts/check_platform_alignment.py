#!/usr/bin/env python3
"""Compare dense RadioMapSolver GT against the live-platform PathSolver sidecar."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
for path in (PACKAGE_ROOT / "src", REPOSITORY_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from uav_rem_active_mapping.data_io import load_sample
from uav_rem_active_mapping.platform_binding import urban_block_binding


def _total_dbm(anchors: list[dict]) -> float:
    return 10.0 * math.log10(sum(10.0 ** (float(item["received_power_dbm"]) / 10.0) for item in anchors))


def _position_from_row_column(sample: dict, row: int, column: int, height_m: float) -> list[float]:
    west, _east, _south, north = (float(value) for value in sample["bounds_enu_m"])
    cell_east, cell_north = (float(value) for value in sample["cell_size_m"])
    return [
        west + (column + 0.5) * cell_east,
        north - (row + 0.5) * cell_north,
        float(height_m),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", type=Path)
    parser.add_argument("--height-index", type=int, default=1)
    parser.add_argument("--asset-dir", type=Path, default=PACKAGE_ROOT / "data" / "sionna_assets" / "platform-alignment")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sample = load_sample(args.sample)
    current_binding = urban_block_binding()
    if sample["platform_world_sha256"].item() != current_binding.world_sha256:
        raise RuntimeError("数据对应的平台世界已变化，拒绝使用旧GT进行平台一致性比较")
    from simulation.rf_engine.sionna_measurement_sidecar import PROFILE_ID, measure

    height_m = float(sample["heights_m"][args.height_index])
    valid = sample["valid_rx_mask"][args.height_index].astype(bool)
    rows, columns = valid.shape
    proposals = [(rows // 8, columns // 8), (rows // 2, columns // 2), (rows * 7 // 8, columns * 7 // 8)]
    points = []
    for row, column in proposals:
        if not valid[row, column]:
            alternatives = np.argwhere(valid)
            row, column = (int(value) for value in alternatives[len(alternatives) // 2])
        position = _position_from_row_column(sample, row, column, height_m)
        observation = measure(
            {"profile_id": PROFILE_ID, "position_m": position, "timestamp": float(len(points))},
            args.asset_dir,
        )
        dense_dbm = float(sample["rss_dbm"][0, args.height_index, row, column])
        online_dbm = _total_dbm(observation["anchors"])
        points.append({
            "row": row,
            "column": column,
            "position_m": position,
            "dense_dbm": dense_dbm,
            "pathsolver_dbm": online_dbm,
            "absolute_error_db": abs(dense_dbm - online_dbm),
        })
    errors = [point["absolute_error_db"] for point in points]
    report = {
        "ok": True,
        "height_m": height_m,
        "sample": str(args.sample),
        "platform_world_sha256": current_binding.world_sha256,
        "point_count": len(points),
        "median_absolute_error_db": float(np.median(errors)),
        "max_absolute_error_db": float(np.max(errors)),
        "points": points,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
