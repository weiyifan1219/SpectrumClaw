from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .contracts import DatasetSpec


@dataclass(frozen=True)
class DatasetConfig:
    output_dir: Path
    split: str
    scene_seeds: tuple[int, ...]
    spec: DatasetSpec
    asset_dir: Path
    samples_per_tx: int
    max_depth: int
    transmitter_mode: str
    source_count_cycle: tuple[int, ...]
    rt_options: dict[str, bool]
    channel_regime: str


def load_dataset_config(path: str | Path) -> DatasetConfig:
    config_path = Path(path)
    package_root = config_path.parents[2]
    raw: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if raw.get("provider") != "sionna":
        raise ValueError("provider 必须是 sionna；正式数据不允许 analytic provider")
    grid = raw.get("grid", {})
    spectrum = raw.get("spectrum", {})
    dataset = raw.get("dataset", {})
    ray_tracing = raw.get("ray_tracing", {})
    spec = DatasetSpec(
        rows=int(grid.get("rows", 128)),
        columns=int(grid.get("columns", 128)),
        frequencies_hz=tuple(float(value) for value in spectrum.get("frequencies_hz", [2.4e9])),
        heights_m=tuple(float(value) for value in grid.get("heights_m", [9, 13, 17, 21, 25])),
        bounds_enu_m=tuple(float(value) for value in grid.get("bounds_enu_m", [-60, 60, -60, 60])),
    )
    seeds = tuple(int(value) for value in dataset.get("scene_seeds", ()))
    if not seeds and "seed_start" in dataset and "scene_count" in dataset:
        seed_start = int(dataset["seed_start"])
        scene_count = int(dataset["scene_count"])
        if scene_count <= 0:
            raise ValueError("dataset.scene_count 必须为正数")
        seeds = tuple(range(seed_start, seed_start + scene_count))
    if not seeds:
        raise ValueError("dataset.scene_seeds 不能为空")
    transmitter_mode = str(dataset.get("transmitter_mode", "random"))
    if transmitter_mode not in {"random", "platform_anchors"}:
        raise ValueError("dataset.transmitter_mode 只能是 random 或 platform_anchors")
    source_count_cycle = tuple(int(value) for value in dataset.get("source_count_cycle", ()))
    if source_count_cycle and any(value not in {1, 2, 3} for value in source_count_cycle):
        raise ValueError("dataset.source_count_cycle 只能包含1、2、3")
    rt_options = {
        "los": bool(ray_tracing.get("los", True)),
        "specular_reflection": bool(ray_tracing.get("specular_reflection", True)),
        "diffuse_reflection": bool(ray_tracing.get("diffuse_reflection", True)),
        "refraction": bool(ray_tracing.get("refraction", True)),
        "diffraction": bool(ray_tracing.get("diffraction", True)),
        "edge_diffraction": bool(ray_tracing.get("edge_diffraction", True)),
    }
    channel_regime = str(ray_tracing.get("channel_regime", "static_deterministic_multipath"))
    if channel_regime != "static_deterministic_multipath":
        raise ValueError("当前 GT 仅支持 static_deterministic_multipath；时变衰落需使用独立episode生成器")
    output = Path(str(dataset.get("output", "artifacts/datasets/pilot")))
    if not output.is_absolute():
        output = (package_root / output).resolve()
    asset_dir = Path(str(ray_tracing.get("asset_dir", "artifacts/sionna-assets")))
    if not asset_dir.is_absolute():
        asset_dir = (package_root / asset_dir).resolve()
    return DatasetConfig(
        output_dir=output,
        split=str(dataset.get("split", "pilot")),
        scene_seeds=seeds,
        spec=spec,
        asset_dir=asset_dir,
        samples_per_tx=int(ray_tracing.get("samples_per_tx", 1_000_000)),
        max_depth=int(ray_tracing.get("max_depth", 2)),
        transmitter_mode=transmitter_mode,
        source_count_cycle=source_count_cycle,
        rt_options=rt_options,
        channel_regime=channel_regime,
    )
