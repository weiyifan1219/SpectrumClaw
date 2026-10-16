from __future__ import annotations

import numpy as np
import pytest


def _valid_sample(spec):
    return {
        "schema_version": np.asarray(spec.schema_version),
        "provider": np.asarray("sionna_rt"),
        "axis_order": np.asarray("FZHW"),
        "sample_id": np.asarray("urban-block-000001"),
        "scene_family_id": np.asarray("urban-block"),
        "scene_id": np.asarray("urban-block/base"),
        "split": np.asarray("pilot"),
        "seed": np.asarray(1, dtype=np.int64),
        "rss_dbm": np.full(spec.shape, -80.0, dtype=np.float32),
        "frequencies_hz": np.asarray(spec.frequencies_hz, dtype=np.float64),
        "heights_m": np.asarray(spec.heights_m, dtype=np.float32),
        "bounds_enu_m": np.asarray(spec.bounds_enu_m, dtype=np.float32),
        "cell_size_m": np.asarray(spec.cell_size_m, dtype=np.float32),
        "building_height_m": np.zeros((spec.rows, spec.columns), dtype=np.float32),
        "building_ids": np.asarray(["building-01"]),
        "building_centres_m": np.asarray([[0.0, 0.0, 5.0]], dtype=np.float32),
        "building_sizes_m": np.asarray([[10.0, 10.0, 10.0]], dtype=np.float32),
        "valid_rx_mask": np.ones((spec.height_count, spec.rows, spec.columns), dtype=np.uint8),
        "flyable_mask": np.ones((spec.height_count, spec.rows, spec.columns), dtype=np.uint8),
        "tx_positions_m": np.asarray([[42.0, 6.0, 24.0]], dtype=np.float32),
        "tx_powers_dbm": np.asarray([[20.0]], dtype=np.float32),
        "tx_orientations_rad": np.zeros((1, 3), dtype=np.float32),
        "material_profile_id": np.asarray("itu-concrete-v1"),
        "scene_asset": np.asarray("urban_block.xml"),
        "platform_world_id": np.asarray("urban_block"),
        "platform_world_sha256": np.asarray("0" * 64),
        "rf_geometry_id": np.asarray("sionna_measurement_sidecar.BUILDINGS.v1"),
        "spatial_frame": np.asarray("local-ENU"),
        "platform_area_m": np.asarray([120.0, 120.0], dtype=np.float32),
        "flight_envelope_bounds_m": np.asarray([-35.0, 35.0, -35.0, 35.0], dtype=np.float32),
        "rt_config_json": np.asarray("{}"),
        "scene_config_json": np.asarray("{}"),
        "generation_config_json": np.asarray("{}"),
        "units_json": np.asarray("{}"),
        "channel_regime": np.asarray("static_deterministic_multipath"),
    }


def test_default_spec_is_single_frequency_five_height_fzhw():
    from uav_rem_active_mapping.contracts import DEFAULT_DATASET_SPEC

    spec = DEFAULT_DATASET_SPEC
    assert spec.shape == (1, 5, 128, 128)
    assert spec.frequencies_hz == (2.4e9,)
    assert spec.heights_m == (9.0, 13.0, 17.0, 21.0, 25.0)
    assert spec.axis_order == "FZHW"


def test_npz_round_trip_preserves_valid_sionna_sample(tmp_path):
    from uav_rem_active_mapping.contracts import DEFAULT_DATASET_SPEC
    from uav_rem_active_mapping.data_io import load_sample, save_sample

    sample = _valid_sample(DEFAULT_DATASET_SPEC)
    path = save_sample(tmp_path / "sample.npz", sample)
    loaded = load_sample(path)

    assert path.is_file()
    assert loaded["provider"].item() == "sionna_rt"
    assert loaded["rss_dbm"].shape == (1, 5, 128, 128)
    np.testing.assert_array_equal(loaded["heights_m"], [9, 13, 17, 21, 25])
    np.testing.assert_array_equal(loaded["building_sizes_m"], [[10, 10, 10]])


def test_contract_rejects_non_sionna_formal_sample():
    from uav_rem_active_mapping.contracts import DEFAULT_DATASET_SPEC, validate_sample

    sample = _valid_sample(DEFAULT_DATASET_SPEC)
    sample["provider"] = np.asarray("analytic")
    with pytest.raises(ValueError, match="provider 必须是 sionna_rt"):
        validate_sample(sample)


def test_contract_rejects_flyable_cells_that_are_not_valid_receivers():
    from uav_rem_active_mapping.contracts import DEFAULT_DATASET_SPEC, validate_sample

    sample = _valid_sample(DEFAULT_DATASET_SPEC)
    sample["valid_rx_mask"][0, 0, 0] = 0
    with pytest.raises(ValueError, match="flyable_mask 必须是 valid_rx_mask 的子集"):
        validate_sample(sample)
