from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .contracts import DatasetSpec


# Versioned snapshot of the geometry shared by Gazebo and the online Sionna
# sidecar. A dedicated consistency test guards this research copy from drift.
BUILDINGS = (
    ("office_east", (13.0, 12.0, 9.0), (10.0, 10.0, 18.0)),
    ("tower_northwest", (-13.0, 14.0, 11.0), (9.0, 8.0, 22.0)),
    ("residential_west", (-16.0, -11.0, 7.5), (12.0, 10.0, 15.0)),
    ("warehouse_southeast", (14.0, -14.0, 5.0), (16.0, 8.0, 10.0)),
    ("library_north", (0.0, 25.0, 5.5), (18.0, 7.0, 11.0)),
    ("clinic_west", (-27.0, 7.0, 6.0), (10.0, 10.0, 12.0)),
)
PLATFORM_ANCHORS = (
    ("tx-01", (42.0, 6.0, 24.0), 20.0),
    ("tx-02", (-42.0, -6.0, 24.0), 20.0),
    ("tx-03", (6.0, 42.0, 24.0), 20.0),
)


@dataclass(frozen=True)
class TransmitterSpec:
    position_m: tuple[float, float, float]
    powers_dbm: tuple[float, ...]
    orientation_rad: tuple[float, float, float]


@dataclass(frozen=True)
class SceneSpec:
    family_id: str
    scene_id: str
    asset_name: str
    material_profile_id: str
    buildings: tuple[tuple[str, tuple[float, float, float], tuple[float, float, float]], ...]
    transmitters: tuple[TransmitterSpec, ...]

    @property
    def transmitter_positions(self) -> np.ndarray:
        return np.asarray([item.position_m for item in self.transmitters], dtype=np.float32)

    def point_inside_building(self, east_m: float, north_m: float) -> bool:
        for _name, center, size in self.buildings:
            if abs(east_m - center[0]) <= size[0] / 2 and abs(north_m - center[1]) <= size[1] / 2:
                return True
        return False

    def raster_masks(self, spec: DatasetSpec) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        east, north = spec.cell_centres()
        building_height = np.zeros((spec.rows, spec.columns), dtype=np.float32)
        for _name, center, size in self.buildings:
            footprint = (
                (np.abs(east - center[0]) <= size[0] / 2)
                & (np.abs(north - center[1]) <= size[1] / 2)
            )
            roof_height = float(center[2] + size[2] / 2)
            building_height[footprint] = np.maximum(building_height[footprint], roof_height)
        valid = np.stack(
            [(building_height < float(height)).astype(np.uint8) for height in spec.heights_m],
            axis=0,
        )
        mission_envelope = (np.abs(east) <= 35.0) & (np.abs(north) <= 35.0)
        flyable = valid * mission_envelope.astype(np.uint8)[None, :, :]
        return building_height, valid, flyable


def urban_block_scene(
    *,
    seed: int,
    frequency_count: int = 1,
    transmitter_mode: str = "random",
    transmitter_count: int | None = None,
) -> SceneSpec:
    if transmitter_mode == "platform_anchors":
        transmitters = tuple(
            TransmitterSpec(
                position_m=tuple(float(value) for value in position),
                powers_dbm=tuple(float(power_dbm) for _ in range(frequency_count)),
                orientation_rad=(0.0, 0.0, 0.0),
            )
            for _identifier, position, power_dbm in PLATFORM_ANCHORS
        )
        return SceneSpec(
            family_id="urban-block",
            scene_id="urban-block/platform-anchors",
            asset_name="urban_block.xml",
            material_profile_id="itu-concrete-v1",
            buildings=tuple(BUILDINGS),
            transmitters=transmitters,
        )
    if transmitter_mode != "random":
        raise ValueError("transmitter_mode 只能是 random 或 platform_anchors")
    rng = np.random.default_rng(int(seed))
    count = int(rng.integers(1, 4)) if transmitter_count is None else int(transmitter_count)
    if count not in {1, 2, 3}:
        raise ValueError("随机场景 transmitter_count 必须属于 {1,2,3}")
    transmitters: list[TransmitterSpec] = []
    for _index in range(count):
        for _attempt in range(2_000):
            east = float(rng.uniform(-54.0, 54.0))
            north = float(rng.uniform(-54.0, 54.0))
            inside = any(
                abs(east - center[0]) <= size[0] / 2 and abs(north - center[1]) <= size[1] / 2
                for _name, center, size in BUILDINGS
            )
            if not inside:
                break
        else:
            raise RuntimeError("无法为 urban_block 采样有效发射源位置")
        transmitters.append(TransmitterSpec(
            position_m=(east, north, float(rng.uniform(1.5, 30.0))),
            powers_dbm=tuple(float(value) for value in rng.uniform(14.0, 24.0, size=frequency_count)),
            orientation_rad=(0.0, 0.0, float(rng.uniform(-np.pi, np.pi))),
        ))
    return SceneSpec(
        family_id="urban-block",
        scene_id="urban-block/base",
        asset_name="urban_block.xml",
        material_profile_id="itu-concrete-v1",
        buildings=tuple(BUILDINGS),
        transmitters=tuple(transmitters),
    )


def with_random_transmitters(
    scene: SceneSpec,
    *,
    seed: int,
    frequency_count: int,
    transmitter_count: int | None = None,
) -> SceneSpec:
    rng = np.random.default_rng(int(seed))
    count = int(rng.integers(1, 4)) if transmitter_count is None else int(transmitter_count)
    if count not in {1, 2, 3}:
        raise ValueError("transmitter_count 必须属于 {1,2,3}")
    transmitters: list[TransmitterSpec] = []
    for _index in range(count):
        for _attempt in range(2_000):
            east = float(rng.uniform(-54.0, 54.0))
            north = float(rng.uniform(-54.0, 54.0))
            if not scene.point_inside_building(east, north):
                break
        else:
            raise RuntimeError("无法为场景采样有效发射源位置")
        transmitters.append(TransmitterSpec(
            position_m=(east, north, float(rng.uniform(1.5, 30.0))),
            powers_dbm=tuple(float(value) for value in rng.uniform(14.0, 24.0, size=frequency_count)),
            orientation_rad=(0.0, 0.0, float(rng.uniform(-np.pi, np.pi))),
        ))
    return SceneSpec(
        family_id=scene.family_id,
        scene_id=scene.scene_id,
        asset_name=scene.asset_name,
        material_profile_id=scene.material_profile_id,
        buildings=scene.buildings,
        transmitters=tuple(transmitters),
    )
