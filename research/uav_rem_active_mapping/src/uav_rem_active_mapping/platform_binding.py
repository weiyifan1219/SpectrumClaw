from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class PlatformBinding:
    world_id: str
    world_sha256: str
    rf_geometry_id: str
    spatial_frame: str
    area_m: tuple[float, float]
    flight_envelope_bounds_m: tuple[float, float, float, float]


def _project_root() -> Path:
    configured = os.environ.get("SPECTRUMCLAW_PROJECT_ROOT")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[4]


def urban_block_binding() -> PlatformBinding:
    world_path = _project_root() / "simulation" / "worlds" / "urban_block.sdf"
    return binding_from_world(
        world_id="urban_block",
        world_path=world_path,
        rf_geometry_id="sionna_measurement_sidecar.BUILDINGS.v1",
    )


def binding_from_world(*, world_id: str, world_path: str | Path, rf_geometry_id: str) -> PlatformBinding:
    world_path = Path(world_path)
    if not world_path.is_file():
        raise FileNotFoundError(f"无法绑定当前平台 world: {world_path}")
    return PlatformBinding(
        world_id=str(world_id),
        world_sha256=hashlib.sha256(world_path.read_bytes()).hexdigest(),
        rf_geometry_id=str(rf_geometry_id),
        spatial_frame="local-ENU",
        area_m=(120.0, 120.0),
        flight_envelope_bounds_m=(-35.0, 35.0, -35.0, 35.0),
    )
