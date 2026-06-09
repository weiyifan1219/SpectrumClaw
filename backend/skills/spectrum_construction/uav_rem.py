"""Agent_UAV_REM result adapter for Spectrum Construction.

The adapter reads existing experiment artifacts from
`/workspace/YiFan/Agent_UAV_REM`. It does not train models or mutate that
project.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_AGENT_UAV_REM_ROOT = Path("/workspace/YiFan/Agent_UAV_REM")

METHOD_TYPES = {
    "ABR": "GeoBelief + Refiner V3",
    "Random": "Random walk sampling",
    "Radio_UNet": "CNN baseline",
    "ViT": "Vision Transformer baseline",
    "DRUE": "Conv autoencoder baseline",
    "KNN": "k-NN interpolation",
    "IDW": "Inverse-distance interpolation",
    "Kriging": "Ordinary kriging",
    "VirtualObstacle": "LOS + path-loss baseline",
    "SBL_GP": "Sparse Bayesian learning + GP",
}

SCENE_FILES = {
    "abr": ("results/abr", "scene_{scene:04d}_abr.npz"),
    "knn": ("results/baselines/knn", "scene_{scene:04d}.npz"),
    "idw": ("results/baselines/idw", "scene_{scene:04d}.npz"),
    "kriging": ("results/baselines/kriging", "scene_{scene:04d}.npz"),
    "drue": ("results/baselines/drue", "scene_{scene:04d}.npz"),
    "virtual_obstacle": ("results/baselines/virtual_obstacle", "scene_{scene:04d}.npz"),
    "sbl_gp": ("results/baselines/sbl_gp", "scene_{scene:04d}.npz"),
}


def build_uav_rem_overview(
    *,
    root: str | Path | None = None,
    scene_id: int = 148,
    height_layer: int = 2,
    method: str = "abr",
) -> dict[str, Any]:
    rem_root = Path(root) if root is not None else _agent_uav_rem_root()
    if not rem_root.exists():
        return _missing_result(rem_root)

    comparison = _load_final_comparison(rem_root / "results" / "final_comparison.csv")
    active_sampling = _load_active_sampling(rem_root / "results" / "abr" / "results.csv")
    scene_options = _discover_scene_options(rem_root)
    selected_scene = scene_id if scene_id in scene_options else (scene_options[0] if scene_options else scene_id)
    scene = _load_scene(rem_root, selected_scene, height_layer, method)

    return {
        "status": "ok",
        "source": {
            "available": True,
            "root": str(rem_root),
            "docs": [
                str(rem_root / "docs" / "README.md"),
                str(rem_root / "docs" / "ALGORITHM_README.md"),
            ],
        },
        "summary": {
            "title": "UAV-Agent REM Construction",
            "goal": "Sparse UAV measurements -> Swin-UNet reconstruction -> active sampling -> REM update",
            "resolution": "128 x 128 x 5",
            "input_channels": ["sampled_rss", "building_map", "observed_mask", "height_map"],
            "current_model": "UAVSwinUNet2D + GeoBelief ABR",
        },
        "tabs": [
            {"id": "active_sampling", "label": "主动采样", "description": "GeoBelief ABR 与 random walk 的采样效率"},
            {"id": "scene_reconstruction", "label": "场景重建", "description": "真实 REM、稀疏采样、重建图和误差图"},
            {"id": "benchmarks", "label": "算法对比", "description": "ABR、Radio_UNet、ViT、KNN、IDW、Kriging 等 RMSE 曲线"},
        ],
        "algorithm_cards": _algorithm_cards(),
        "comparison": comparison,
        "active_sampling": active_sampling,
        "scene_options": scene_options,
        "scene": scene,
    }


def _missing_result(rem_root: Path) -> dict[str, Any]:
    return {
        "status": "ok",
        "source": {
            "available": False,
            "root": str(rem_root),
            "docs": [],
        },
        "summary": {
            "title": "UAV-Agent REM Construction",
            "goal": "Waiting for Agent_UAV_REM artifacts",
            "resolution": "128 x 128 x 5",
            "input_channels": [],
            "current_model": "unavailable",
        },
        "tabs": [],
        "algorithm_cards": _algorithm_cards(),
        "comparison": {"rates": [], "methods": []},
        "active_sampling": {"rates": [], "policies": []},
        "scene_options": [],
        "scene": None,
    }


def _load_final_comparison(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"rates": [], "methods": []}

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    rates = [float(name) for name in rows[0].keys() if name != "Method"] if rows else []
    methods = []
    for row in rows:
        values = [float(row[f"{rate:.4f}"]) for rate in rates]
        methods.append(
            {
                "method": row["Method"],
                "type": METHOD_TYPES.get(row["Method"], "baseline"),
                "rmse": values,
                "mean_rmse": round(float(np.mean(values)), 4),
                "best_rmse": round(float(np.min(values)), 4),
            }
        )
    methods.sort(key=lambda item: item["mean_rmse"])
    return {"rates": rates, "methods": methods}


def _load_active_sampling(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"rates": [], "policies": []}

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    rate_columns = [name for name in rows[0].keys() if name.startswith("rmse_")] if rows else []
    if rows and not rate_columns and "rmse" in rows[0]:
        values = [float(row["rmse"]) for row in rows]
        method_name = rows[0].get("method") or rows[0].get("policy") or "ABR"
        return {
            "rates": [],
            "policies": [
                {
                    "policy": method_name,
                    "rmse": [],
                    "mean_rmse": round(float(np.mean(values)), 4),
                    "mean_samples": None,
                    "mean_elapsed": None,
                }
            ],
        }

    rates = [float(name.replace("rmse_", "")) for name in rate_columns]
    by_policy: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_policy.setdefault(row.get("policy") or row.get("method") or "ABR", []).append(row)

    policies = []
    for policy, policy_rows in sorted(by_policy.items()):
        values = []
        for column in rate_columns:
            values.append(round(float(np.mean([float(row[column]) for row in policy_rows])), 4))
        policies.append(
            {
                "policy": policy,
                "rmse": values,
                "mean_rmse": round(float(np.mean(values)), 4) if values else None,
                "mean_samples": _optional_mean(policy_rows, "n_samples"),
                "mean_elapsed": _optional_mean(policy_rows, "elapsed"),
            }
        )

    policies.sort(key=lambda item: item["mean_rmse"] if item["mean_rmse"] is not None else 999)
    return {"rates": rates, "policies": policies}


def _optional_mean(rows: list[dict[str, str]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) not in (None, "")]
    if not values:
        return None
    return round(float(np.mean(values)), 1)


def _discover_scene_options(rem_root: Path) -> list[int]:
    scene_ids: set[int] = set()
    for directory, pattern in SCENE_FILES.values():
        prefix, suffix = pattern.split("{scene:04d}")
        for path in (rem_root / directory).glob(f"{prefix}*{suffix}"):
            scene_text = path.name.removeprefix(prefix).removesuffix(suffix)
            if scene_text.isdigit():
                scene_ids.add(int(scene_text))
    return sorted(scene_ids)


def _load_scene(rem_root: Path, scene_id: int, height_layer: int, method: str) -> dict[str, Any] | None:
    method_key = method.lower()
    directory, pattern = SCENE_FILES.get(method_key, SCENE_FILES["abr"])
    path = rem_root / directory / pattern.format(scene=scene_id)
    if not path.exists():
        path = _first_scene_file(rem_root / directory)
    if path is None or not path.exists():
        return None

    data = np.load(path, allow_pickle=True)
    gt = _array(data, "gt_map")
    pred = _array(data, "pred_map")
    sampled = _array(data, "sampled_map")
    valid = _array(data, "valid_mask")
    building = _array(data, "building_map", fallback=np.zeros_like(gt))

    layer = int(max(0, min(height_layer, gt.shape[0] - 1)))
    gt_layer = gt[layer]
    pred_layer = pred[layer]
    valid_layer = valid[layer]
    sampled_layer = np.where(valid_layer > 0.5, gt_layer if sampled is None else sampled[layer], np.nan)
    error_layer = np.abs(gt_layer - pred_layer)
    building_layer = building[layer] if building is not None else np.zeros_like(gt_layer)
    rmse = float(data["rmse"]) if "rmse" in data.files else float(np.sqrt(np.nanmean((gt - pred) ** 2)))

    return {
        "scene_id": int(_scalar(data, "scene_id", scene_id)),
        "method": method_key,
        "height_layer": layer,
        "height_count": int(gt.shape[0]),
        "rmse": round(rmse, 4),
        "sample_count": int(np.sum(valid > 0.5)),
        "coverage_ratio": round(float(np.mean(valid > 0.5)), 6),
        "path_points": _path_points(data, layer, gt.shape[-2], gt.shape[-1]),
        "metrics": _metrics(gt_layer),
        "error_metrics": _error_metrics(error_layer),
        "maps": {
            "ground_truth": _matrix_for_json(gt_layer),
            "sampled": _matrix_for_json(sampled_layer),
            "reconstruction": _matrix_for_json(pred_layer),
            "error": _matrix_for_json(error_layer),
            "observed_mask": valid_layer.astype(int).tolist(),
            "building_map": building_layer.astype(float).tolist(),
        },
    }


def _first_scene_file(directory: Path) -> Path | None:
    files = sorted(directory.glob("scene_*.npz"))
    return files[0] if files else None


def _array(data: Any, key: str, fallback: np.ndarray | None = None) -> np.ndarray:
    if key in data.files:
        return np.asarray(data[key], dtype=np.float32)
    if fallback is not None:
        return fallback
    raise KeyError(key)


def _scalar(data: Any, key: str, fallback: int) -> int:
    if key not in data.files:
        return fallback
    return int(np.asarray(data[key]).item())


def _path_points(data: Any, layer: int, height: int, width: int) -> list[list[float]]:
    if "path_coords" not in data.files:
        return []
    coords = np.asarray(data["path_coords"])
    if coords.ndim != 2 or coords.shape[1] < 3:
        return []
    coords = coords[coords[:, 0] == layer]
    if coords.size == 0:
        return []
    stride = max(1, len(coords) // 180)
    points = []
    for _, y, x in coords[::stride]:
        points.append([
            round(float(x) / max(width - 1, 1) * 100, 3),
            round(float(y) / max(height - 1, 1) * 100, 3),
        ])
    return points


def _matrix_for_json(matrix: np.ndarray) -> list[list[float | None]]:
    clean = np.where(np.isfinite(matrix), np.round(matrix, 4), np.nan)
    rows: list[list[float | None]] = []
    for row in clean.tolist():
        rows.append([None if np.isnan(value) else float(value) for value in row])
    return rows


def _metrics(matrix: np.ndarray) -> dict[str, float]:
    return {
        "min_dbm": round(float(np.nanmin(matrix)), 4),
        "max_dbm": round(float(np.nanmax(matrix)), 4),
        "mean_dbm": round(float(np.nanmean(matrix)), 4),
    }


def _error_metrics(matrix: np.ndarray) -> dict[str, float]:
    return {
        "min_dbm": round(float(np.nanmin(matrix)), 4),
        "max_dbm": round(float(np.nanmax(matrix)), 4),
        "mean_dbm": round(float(np.nanmean(matrix)), 4),
    }


def _algorithm_cards() -> list[dict[str, str]]:
    return [
        {
            "name": "GeoBelief ABR",
            "role": "active sampling",
            "description": "Uncertainty, boundary, innovation, shadow and coverage terms select UAV measurement waypoints.",
        },
        {
            "name": "UAVSwinUNet2D",
            "role": "REM reconstruction",
            "description": "Folds five height layers into channels and reconstructs the full 128 x 128 x 5 RSS map.",
        },
        {
            "name": "Coverage planner",
            "role": "sampling baseline",
            "description": "Greedily targets the largest unobserved region using distance transform.",
        },
        {
            "name": "Traditional baselines",
            "role": "comparison",
            "description": "KNN, IDW, Kriging, DRUE, Radio_UNet, ViT and VirtualObstacle results are read from existing artifacts.",
        },
    ]


def _agent_uav_rem_root() -> Path:
    return Path(os.environ.get("SPECTRUMCLAW_AGENT_UAV_REM_ROOT", DEFAULT_AGENT_UAV_REM_ROOT))
