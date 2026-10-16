from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np

from .contracts import DEFAULT_DATASET_SPEC, DatasetSpec
from .data_io import atomic_write_text, load_sample, save_sample
from .generation import SionnaPlaneProvider, generate_scene_sample
from .platform_binding import PlatformBinding, urban_block_binding
from .scenes import urban_block_scene


def build_dataset(
    *,
    output_dir: str | Path,
    provider: SionnaPlaneProvider,
    scene_seeds: Iterable[int],
    split: str,
    spec: DatasetSpec = DEFAULT_DATASET_SPEC,
    transmitter_mode: str = "random",
    source_count_cycle: tuple[int, ...] = (),
    platform_binding: PlatformBinding | None = None,
) -> dict:
    destination = Path(output_dir)
    selected_seeds = [int(seed) for seed in scene_seeds]
    if not selected_seeds:
        raise ValueError("scene_seeds 不能为空")
    binding = platform_binding or urban_block_binding()
    manifest_path = destination / "manifest.json"
    existing_manifest = None
    existing_samples: list[dict] = []
    existing_seeds: set[int] = set()
    if manifest_path.is_file():
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing_samples = list(existing_manifest.get("samples", []))
        existing_seeds = {int(item["seed"]) for item in existing_samples}
    else:
        for index, seed in enumerate(selected_seeds):
            sample_id = f"urban-block-{seed:08d}"
            path = destination / split / f"{sample_id}.npz"
            if not path.is_file():
                continue
            archive = load_sample(path, spec)
            if int(archive["seed"].item()) != seed or str(archive["split"].item()) != split:
                raise ValueError(f"断点样本seed/split不符: {path}")
            transmitter_count = int(archive["tx_positions_m"].shape[0])
            existing_samples.append({
                "path": str(path.relative_to(destination)),
                "sample_id": sample_id,
                "scene_family_id": "urban-block",
                "scene_id": "urban-block/base",
                "split": split,
                "seed": seed,
                "transmitter_count": transmitter_count,
                "platform_world_sha256": binding.world_sha256,
            })
            existing_seeds.add(seed)
    samples = []
    for index, seed in enumerate(selected_seeds):
        if seed in existing_seeds:
            continue
        transmitter_count = source_count_cycle[index % len(source_count_cycle)] if source_count_cycle else None
        scene = urban_block_scene(
            seed=seed,
            frequency_count=spec.frequency_count,
            transmitter_mode=transmitter_mode,
            transmitter_count=transmitter_count,
        )
        sample = generate_scene_sample(
            provider=provider,
            spec=spec,
            scene=scene,
            split=split,
            seed=seed,
            platform_binding=binding,
        )
        filename = f"{sample['sample_id'].item()}.npz"
        path = save_sample(destination / split / filename, sample, spec)
        samples.append({
            "path": str(path.relative_to(destination)),
            "sample_id": sample["sample_id"].item(),
            "scene_family_id": sample["scene_family_id"].item(),
            "scene_id": sample["scene_id"].item(),
            "split": split,
            "seed": seed,
            "transmitter_count": int(sample["tx_positions_m"].shape[0]),
            "platform_world_sha256": sample["platform_world_sha256"].item(),
        })
    manifest = {
        "schema_version": spec.schema_version,
        "provider": provider.provider_name,
        "axis_order": spec.axis_order,
        "shape": list(spec.shape),
        "frequencies_hz": list(spec.frequencies_hz),
        "heights_m": list(spec.heights_m),
        "bounds_enu_m": list(spec.bounds_enu_m),
        "sample_count": len(existing_samples) + len(samples),
        "platform_world_id": binding.world_id,
        "platform_world_sha256": binding.world_sha256,
        "rf_geometry_id": binding.rf_geometry_id,
        "transmitter_mode": transmitter_mode,
        "source_count_cycle": list(source_count_cycle),
        "samples": [*existing_samples, *samples],
    }
    if existing_manifest is not None:
        for field in ("schema_version", "provider", "axis_order", "shape", "frequencies_hz", "heights_m", "bounds_enu_m", "platform_world_sha256", "rf_geometry_id"):
            if existing_manifest.get(field) != manifest.get(field):
                raise ValueError(f"已有manifest字段不兼容: {field}")
    destination.mkdir(parents=True, exist_ok=True)
    atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest
