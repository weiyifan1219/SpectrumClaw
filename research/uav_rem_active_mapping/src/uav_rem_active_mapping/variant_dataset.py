from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np

from .contracts import DEFAULT_DATASET_SPEC, DatasetSpec
from .data_io import atomic_write_text, load_sample, save_sample
from .generation import SionnaPlaneProvider, generate_scene_sample
from .platform_binding import binding_from_world
from .scene_variants import export_layout_assets, urban_layout
from .scenes import with_random_transmitters


def build_layout_dataset(
    *,
    output_root: str | Path,
    asset_root: str | Path,
    provider: SionnaPlaneProvider,
    layout_index: int,
    split: str,
    source_seeds: Iterable[int],
    spec: DatasetSpec = DEFAULT_DATASET_SPEC,
    source_count_cycle: tuple[int, ...] = (1, 2, 3),
) -> dict:
    seeds = [int(seed) for seed in source_seeds]
    if not seeds:
        raise ValueError("source_seeds 不能为空")
    base_scene = urban_layout(layout_index=layout_index, split=split)
    assets = export_layout_assets(base_scene, asset_root, split=split)
    binding = binding_from_world(
        world_id=base_scene.scene_id,
        world_path=assets.gazebo_world_path,
        rf_geometry_id=f"canonical_scene.{base_scene.scene_id}.v1",
    )
    root = Path(output_root) / base_scene.scene_id
    manifest_path = root / "manifest.json"
    existing_samples = []
    existing_seeds: set[int] = set()
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        for field, expected in (
            ("schema_version", spec.schema_version),
            ("provider", provider.provider_name),
            ("axis_order", spec.axis_order),
            ("shape", list(spec.shape)),
            ("frequencies_hz", list(spec.frequencies_hz)),
            ("heights_m", list(spec.heights_m)),
            ("bounds_enu_m", list(spec.bounds_enu_m)),
            ("scene_id", base_scene.scene_id),
            ("platform_world_sha256", binding.world_sha256),
            ("rf_geometry_id", binding.rf_geometry_id),
        ):
            if existing.get(field) != expected:
                raise ValueError(f"已有manifest字段不兼容: {field}")
        existing_samples = list(existing.get("samples", []))
        existing_seeds = {int(item["seed"]) for item in existing_samples}
    else:
        # Recover completed immutable samples after an interrupted worker. NPZ
        # files are validated by opening their central directory and checking
        # the embedded seed/schema before they are admitted to the manifest.
        for index, seed in enumerate(seeds):
            sample_id = f"{base_scene.family_id}-{seed:08d}"
            path = root / split / f"{sample_id}.npz"
            if not path.is_file():
                continue
            archive = load_sample(path, spec)
            if int(archive["seed"].item()) != seed or str(archive["split"].item()) != split:
                raise ValueError(f"断点样本seed/split不符: {path}")
            existing_samples.append({
                "path": str(path.relative_to(root)),
                "sample_id": sample_id,
                "seed": seed,
                "split": split,
                "transmitter_count": int(archive["tx_positions_m"].shape[0]),
            })
            existing_seeds.add(seed)
    samples = []
    for index, seed in enumerate(seeds):
        if seed in existing_seeds:
            continue
        count = source_count_cycle[index % len(source_count_cycle)]
        scene = with_random_transmitters(
            base_scene,
            seed=seed,
            frequency_count=spec.frequency_count,
            transmitter_count=count,
        )
        sample = generate_scene_sample(
            provider=provider,
            scene=scene,
            split=split,
            seed=seed,
            spec=spec,
            platform_binding=binding,
        )
        path = save_sample(root / split / f"{sample['sample_id'].item()}.npz", sample, spec)
        samples.append({
            "path": str(path.relative_to(root)),
            "sample_id": sample["sample_id"].item(),
            "seed": seed,
            "split": split,
            "transmitter_count": count,
        })
    manifest = {
        "schema_version": spec.schema_version,
        "provider": provider.provider_name,
        "axis_order": spec.axis_order,
        "shape": list(spec.shape),
        "frequencies_hz": list(spec.frequencies_hz),
        "heights_m": list(spec.heights_m),
        "bounds_enu_m": list(spec.bounds_enu_m),
        "scene_id": base_scene.scene_id,
        "scene_family_id": base_scene.family_id,
        "split": split,
        "platform_world_id": binding.world_id,
        "platform_world_sha256": binding.world_sha256,
        "rf_geometry_id": binding.rf_geometry_id,
        "gazebo_world": str(assets.gazebo_world_path),
        "sionna_xml": str(assets.sionna_xml_path),
        "source_count_cycle": list(source_count_cycle),
        "sample_count": len(existing_samples) + len(samples),
        "samples": [*existing_samples, *samples],
    }
    root.mkdir(parents=True, exist_ok=True)
    atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
    return {**manifest, "manifest_path": root / "manifest.json", "gazebo_world": assets.gazebo_world_path, "sionna_xml": assets.sionna_xml_path}
