from __future__ import annotations

import json
from typing import Protocol

import numpy as np

from .contracts import DEFAULT_DATASET_SPEC, DatasetSpec, validate_sample
from .platform_binding import PlatformBinding, urban_block_binding
from .scenes import SceneSpec


class SionnaPlaneProvider(Protocol):
    provider_name: str

    def generate_total_rss(
        self,
        *,
        spec: DatasetSpec,
        scene: SceneSpec,
        frequency_hz: float,
        height_m: float,
        seed: int,
    ) -> np.ndarray: ...


def generate_scene_sample(
    *,
    provider: SionnaPlaneProvider,
    scene: SceneSpec,
    split: str,
    seed: int,
    spec: DatasetSpec = DEFAULT_DATASET_SPEC,
    platform_binding: PlatformBinding | None = None,
) -> dict[str, np.ndarray]:
    if provider.provider_name != "sionna_rt":
        raise ValueError("正式数据 provider 必须是 sionna_rt")
    frequency_maps = []
    plane_seeds = np.zeros((spec.frequency_count, spec.height_count), dtype=np.uint64)
    plane_attempts = np.zeros_like(plane_seeds, dtype=np.uint8)
    for frequency_index, frequency_hz in enumerate(spec.frequencies_hz):
        height_maps = []
        for height_index, height_m in enumerate(spec.heights_m):
            requested_seed = int(seed) * 10_000 + frequency_index * 100 + height_index
            plane = np.asarray(provider.generate_total_rss(
                spec=spec,
                scene=scene,
                frequency_hz=float(frequency_hz),
                height_m=float(height_m),
                seed=requested_seed,
            ), dtype=np.float32)
            plane_seeds[frequency_index, height_index] = int(getattr(provider, "last_plane_seed", requested_seed)) % (2**32)
            plane_attempts[frequency_index, height_index] = int(getattr(provider, "last_plane_attempts", 1))
            if plane.shape != (spec.rows, spec.columns):
                raise ValueError("Sionna 平面形状必须是 [H,W]")
            height_maps.append(plane)
        frequency_maps.append(np.stack(height_maps, axis=0))
    building_height, valid, flyable = scene.raster_masks(spec)
    binding = platform_binding or urban_block_binding()
    is_platform_scene = binding.world_id == "urban_block" and scene.family_id == "urban-block"
    is_generated_scene = binding.world_id == scene.scene_id
    if not (is_platform_scene or is_generated_scene):
        raise ValueError("场景与平台绑定不匹配")
    rt_metadata = getattr(provider, "rt_metadata", lambda: {"engine": "sionna_rt", "test_provider": True})()
    building_ids = [name for name, _center, _size in scene.buildings]
    building_centres = [center for _name, center, _size in scene.buildings]
    building_sizes = [size for _name, _center, size in scene.buildings]
    scene_config = {
        "family_id": scene.family_id,
        "scene_id": scene.scene_id,
        "asset_name": scene.asset_name,
        "material_profile_id": scene.material_profile_id,
        "buildings": [
            {"id": name, "center_m": list(center), "size_m": list(size)}
            for name, center, size in scene.buildings
        ],
        "transmitters": [
            {
                "position_m": list(transmitter.position_m),
                "powers_dbm": list(transmitter.powers_dbm),
                "orientation_rad": list(transmitter.orientation_rad),
            }
            for transmitter in scene.transmitters
        ],
    }
    generation_config = {
        "axis_order": spec.axis_order,
        "shape": list(spec.shape),
        "frequencies_hz": list(spec.frequencies_hz),
        "heights_m": list(spec.heights_m),
        "bounds_enu_m": list(spec.bounds_enu_m),
        "cell_size_m": list(spec.cell_size_m),
        "ray_tracing": rt_metadata,
        "ray_seed_rule": "(source_seed*10000 + frequency_index*100 + height_index + retry_index) mod 2**32; retry_index=0..2",
        "channel_regime": "static_deterministic_multipath",
    }
    sample = {
        "schema_version": np.asarray(spec.schema_version),
        "provider": np.asarray(provider.provider_name),
        "axis_order": np.asarray(spec.axis_order),
        "sample_id": np.asarray(f"{scene.family_id}-{int(seed):08d}"),
        "scene_family_id": np.asarray(scene.family_id),
        "scene_id": np.asarray(scene.scene_id),
        "split": np.asarray(str(split)),
        "seed": np.asarray(int(seed), dtype=np.int64),
        "rss_dbm": np.stack(frequency_maps, axis=0).astype(np.float32),
        "rt_plane_seeds": plane_seeds,
        "rt_plane_attempts": plane_attempts,
        "frequencies_hz": np.asarray(spec.frequencies_hz, dtype=np.float64),
        "heights_m": np.asarray(spec.heights_m, dtype=np.float32),
        "bounds_enu_m": np.asarray(spec.bounds_enu_m, dtype=np.float32),
        "cell_size_m": np.asarray(spec.cell_size_m, dtype=np.float32),
        "building_height_m": building_height,
        "building_ids": np.asarray(building_ids),
        "building_centres_m": np.asarray(building_centres, dtype=np.float32),
        "building_sizes_m": np.asarray(building_sizes, dtype=np.float32),
        "valid_rx_mask": valid,
        "flyable_mask": flyable,
        "tx_positions_m": scene.transmitter_positions,
        "tx_powers_dbm": np.asarray([item.powers_dbm for item in scene.transmitters], dtype=np.float32),
        "tx_orientations_rad": np.asarray([item.orientation_rad for item in scene.transmitters], dtype=np.float32),
        "material_profile_id": np.asarray(scene.material_profile_id),
        "scene_asset": np.asarray(scene.asset_name),
        "platform_world_id": np.asarray(binding.world_id),
        "platform_world_sha256": np.asarray(binding.world_sha256),
        "rf_geometry_id": np.asarray(binding.rf_geometry_id),
        "spatial_frame": np.asarray(binding.spatial_frame),
        "platform_area_m": np.asarray(binding.area_m, dtype=np.float32),
        "flight_envelope_bounds_m": np.asarray(binding.flight_envelope_bounds_m, dtype=np.float32),
        "rt_config_json": np.asarray(json.dumps(rt_metadata, sort_keys=True)),
        "scene_config_json": np.asarray(json.dumps(scene_config, sort_keys=True)),
        "generation_config_json": np.asarray(json.dumps(generation_config, sort_keys=True)),
        "units_json": np.asarray(json.dumps({
            "rss_dbm": "dBm",
            "frequencies_hz": "Hz",
            "heights_m": "m",
            "positions": "m in local-ENU",
            "orientations": "rad",
            "building_sizes": "m",
        }, sort_keys=True)),
        "channel_regime": np.asarray("static_deterministic_multipath"),
    }
    validate_sample(sample, spec)
    return sample
