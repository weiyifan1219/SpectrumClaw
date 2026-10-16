from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np


SCHEMA_VERSION = "spectrumclaw.uav-rem.fzhw.v4"
AXIS_ORDER = "FZHW"


@dataclass(frozen=True)
class DatasetSpec:
    rows: int = 128
    columns: int = 128
    frequencies_hz: tuple[float, ...] = (2.4e9,)
    heights_m: tuple[float, ...] = (9.0, 13.0, 17.0, 21.0, 25.0)
    bounds_enu_m: tuple[float, float, float, float] = (-60.0, 60.0, -60.0, 60.0)
    schema_version: str = SCHEMA_VERSION
    axis_order: str = AXIS_ORDER

    def __post_init__(self) -> None:
        if self.rows != 128 or self.columns != 128:
            raise ValueError("v1 数据集空间网格必须是 128×128")
        if self.axis_order != AXIS_ORDER:
            raise ValueError("数据轴顺序必须是 FZHW")
        if not self.frequencies_hz or not all(math.isfinite(value) and value > 0 for value in self.frequencies_hz):
            raise ValueError("frequencies_hz 必须包含有限正数")
        if len(self.heights_m) != 5 or tuple(sorted(set(self.heights_m))) != self.heights_m:
            raise ValueError("heights_m 必须包含五个唯一且递增的高度")
        west, east, south, north = self.bounds_enu_m
        if not west < east or not south < north:
            raise ValueError("bounds_enu_m 无效")

    @property
    def frequency_count(self) -> int:
        return len(self.frequencies_hz)

    @property
    def height_count(self) -> int:
        return len(self.heights_m)

    @property
    def shape(self) -> tuple[int, int, int, int]:
        return self.frequency_count, self.height_count, self.rows, self.columns

    @property
    def cell_size_m(self) -> tuple[float, float]:
        west, east, south, north = self.bounds_enu_m
        return (east - west) / self.columns, (north - south) / self.rows

    def cell_centres(self) -> tuple[np.ndarray, np.ndarray]:
        west, _east, _south, north = self.bounds_enu_m
        cell_east, cell_north = self.cell_size_m
        east = west + (np.arange(self.columns, dtype=np.float64) + 0.5) * cell_east
        northing = north - (np.arange(self.rows, dtype=np.float64) + 0.5) * cell_north
        return np.meshgrid(east, northing)


DEFAULT_DATASET_SPEC = DatasetSpec()


def _scalar(sample: Mapping[str, Any], key: str) -> Any:
    if key not in sample:
        raise ValueError(f"样本缺少字段: {key}")
    value = np.asarray(sample.get(key))
    if value.shape != ():
        raise ValueError(f"{key} 必须是标量")
    return value.item()


def _shape(sample: Mapping[str, Any], key: str, expected: tuple[int, ...]) -> np.ndarray:
    if key not in sample:
        raise ValueError(f"样本缺少字段: {key}")
    value = np.asarray(sample[key])
    if value.shape != expected:
        raise ValueError(f"{key} 形状应为 {expected}，实际为 {value.shape}")
    return value


def validate_sample(sample: Mapping[str, Any], spec: DatasetSpec = DEFAULT_DATASET_SPEC) -> None:
    if _scalar(sample, "schema_version") != spec.schema_version:
        raise ValueError(f"schema_version 必须是 {spec.schema_version}")
    if _scalar(sample, "provider") != "sionna_rt":
        raise ValueError("正式数据 provider 必须是 sionna_rt")
    if _scalar(sample, "axis_order") != spec.axis_order:
        raise ValueError("axis_order 必须是 FZHW")

    rss = _shape(sample, "rss_dbm", spec.shape)
    if not np.all(np.isfinite(rss)):
        raise ValueError("rss_dbm 必须全部有限")
    frequencies = _shape(sample, "frequencies_hz", (spec.frequency_count,))
    heights = _shape(sample, "heights_m", (spec.height_count,))
    if not np.array_equal(frequencies.astype(float), np.asarray(spec.frequencies_hz, dtype=float)):
        raise ValueError("frequencies_hz 与数据契约不一致")
    if not np.array_equal(heights.astype(float), np.asarray(spec.heights_m, dtype=float)):
        raise ValueError("heights_m 与数据契约不一致")
    _shape(sample, "bounds_enu_m", (4,))
    _shape(sample, "cell_size_m", (2,))
    _shape(sample, "building_height_m", (spec.rows, spec.columns))
    building_ids = np.asarray(sample.get("building_ids"))
    building_centres = np.asarray(sample.get("building_centres_m"))
    building_sizes = np.asarray(sample.get("building_sizes_m"))
    if building_ids.ndim != 1 or building_ids.size < 1:
        raise ValueError("building_ids 必须是非空 [B]")
    if building_centres.shape != (building_ids.size, 3):
        raise ValueError("building_centres_m 必须是 [B,3]")
    if building_sizes.shape != (building_ids.size, 3) or np.any(building_sizes <= 0):
        raise ValueError("building_sizes_m 必须是正数 [B,3]")
    if len(set(str(value) for value in building_ids.tolist())) != building_ids.size:
        raise ValueError("building_ids 必须唯一")
    valid = _shape(sample, "valid_rx_mask", (spec.height_count, spec.rows, spec.columns))
    flyable = _shape(sample, "flyable_mask", (spec.height_count, spec.rows, spec.columns))
    if not np.all((valid == 0) | (valid == 1)) or not np.all((flyable == 0) | (flyable == 1)):
        raise ValueError("valid_rx_mask 和 flyable_mask 必须是二值掩码")
    if np.any((flyable == 1) & (valid == 0)):
        raise ValueError("flyable_mask 必须是 valid_rx_mask 的子集")

    positions = np.asarray(sample.get("tx_positions_m"))
    powers = np.asarray(sample.get("tx_powers_dbm"))
    orientations = np.asarray(sample.get("tx_orientations_rad"))
    if positions.ndim != 2 or positions.shape[1:] != (3,) or not 1 <= positions.shape[0] <= 3:
        raise ValueError("tx_positions_m 必须是 [N,3] 且 1<=N<=3")
    if powers.shape != (positions.shape[0], spec.frequency_count):
        raise ValueError("tx_powers_dbm 必须是 [N,F]")
    if orientations.shape != (positions.shape[0], 3):
        raise ValueError("tx_orientations_rad 必须是 [N,3]")
    for key in ("building_centres_m", "building_sizes_m", "building_height_m", "tx_positions_m", "tx_powers_dbm", "tx_orientations_rad", "bounds_enu_m", "cell_size_m"):
        if not np.isfinite(np.asarray(sample[key])).all():
            raise ValueError(f"{key} 必须全部有限")
    for key in (
        "sample_id", "scene_family_id", "scene_id", "split", "seed", "material_profile_id", "scene_asset",
        "platform_world_id", "platform_world_sha256", "rf_geometry_id", "spatial_frame",
        "rt_config_json", "channel_regime",
        "scene_config_json", "generation_config_json", "units_json",
    ):
        _scalar(sample, key)
    if _scalar(sample, "spatial_frame") != "local-ENU":
        raise ValueError("spatial_frame 必须是 local-ENU")
    _shape(sample, "platform_area_m", (2,))
    _shape(sample, "flight_envelope_bounds_m", (4,))
