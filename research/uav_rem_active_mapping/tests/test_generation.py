from __future__ import annotations

import numpy as np


class RecordingSionnaProvider:
    provider_name = "sionna_rt"

    def __init__(self):
        self.calls = []

    def generate_total_rss(self, *, spec, scene, frequency_hz, height_m, seed):
        self.calls.append((frequency_hz, height_m, seed, len(scene.transmitters)))
        return np.full(
            (spec.rows, spec.columns),
            -90.0 + 0.1 * float(height_m),
            dtype=np.float32,
        )


def test_generator_calls_sionna_once_per_frequency_height_plane():
    from uav_rem_active_mapping.contracts import DEFAULT_DATASET_SPEC
    from uav_rem_active_mapping.generation import generate_scene_sample
    from uav_rem_active_mapping.scenes import urban_block_scene

    provider = RecordingSionnaProvider()
    sample = generate_scene_sample(
        provider=provider,
        spec=DEFAULT_DATASET_SPEC,
        scene=urban_block_scene(seed=7),
        split="pilot",
        seed=7,
    )

    assert len(provider.calls) == 5
    assert [call[1] for call in provider.calls] == [9.0, 13.0, 17.0, 21.0, 25.0]
    assert sample["rss_dbm"].shape == (1, 5, 128, 128)
    assert sample["provider"].item() == "sionna_rt"
    assert np.all(sample["rss_dbm"][0, 0] == np.float32(-89.1))
    assert sample["building_centres_m"].shape[1] == 3
    assert sample["building_sizes_m"].shape == sample["building_centres_m"].shape
    assert sample["building_ids"].shape[0] == sample["building_centres_m"].shape[0]
    assert "transmitters" in str(sample["scene_config_json"].item())


def test_scene_seed_reproduces_transmitters_and_keeps_them_outside_buildings():
    from uav_rem_active_mapping.scenes import urban_block_scene

    first = urban_block_scene(seed=19)
    second = urban_block_scene(seed=19)

    np.testing.assert_array_equal(first.transmitter_positions, second.transmitter_positions)
    assert 1 <= len(first.transmitters) <= 3
    for transmitter in first.transmitters:
        assert not first.point_inside_building(transmitter.position_m[0], transmitter.position_m[1])


def test_height_masks_exclude_buildings_that_reach_each_plane():
    from uav_rem_active_mapping.contracts import DEFAULT_DATASET_SPEC
    from uav_rem_active_mapping.scenes import urban_block_scene

    scene = urban_block_scene(seed=3)
    building_height, valid, flyable = scene.raster_masks(DEFAULT_DATASET_SPEC)

    assert building_height.shape == (128, 128)
    assert valid.shape == (5, 128, 128)
    assert flyable.shape == (5, 128, 128)
    assert np.count_nonzero(valid[0] == 0) >= np.count_nonzero(valid[-1] == 0)
    assert np.all(flyable <= valid)


def test_gt_visualization_mask_is_black_only_inside_buildings_at_the_selected_height():
    import importlib.util
    from pathlib import Path

    script = Path(__file__).parents[1] / "scripts" / "plot_gt.py"
    module_spec = importlib.util.spec_from_file_location("plot_gt", script)
    module = importlib.util.module_from_spec(module_spec)
    assert module_spec.loader is not None
    module_spec.loader.exec_module(module)

    rss = np.full((2, 3), -70.0, dtype=np.float32)
    valid = np.asarray([[1, 0, 1], [0, 1, 1]], dtype=np.uint8)
    masked = module.mask_invalid_receivers(rss, valid)

    assert masked.mask.tolist() == [[False, True, False], [True, False, False]]
    assert masked[0, 0] == np.float32(-70.0)


def test_research_geometry_matches_online_sionna_scene():
    from simulation.rf_engine.sionna_measurement_sidecar import BUILDINGS as ONLINE_BUILDINGS
    from uav_rem_active_mapping.scenes import BUILDINGS as RESEARCH_BUILDINGS

    assert RESEARCH_BUILDINGS == ONLINE_BUILDINGS


def test_sionna_provider_sums_transmitters_in_watts_and_flips_rows(tmp_path):
    from uav_rem_active_mapping.contracts import DatasetSpec
    from uav_rem_active_mapping.scenes import urban_block_scene
    from uav_rem_active_mapping.sionna_provider import SionnaRadioMapProvider

    spec = DatasetSpec(rows=128, columns=128)
    raw = np.zeros((2, 128, 128), dtype=np.float64)
    raw[0] = 1e-9
    raw[1] = 1e-9
    raw[:, 0, :] = 2e-9
    captured = {}

    def solve_plane(**kwargs):
        captured.update(kwargs)
        return raw

    provider = SionnaRadioMapProvider(asset_dir=tmp_path, solve_plane=solve_plane)
    scene = urban_block_scene(seed=1)
    result = provider.generate_total_rss(
        spec=spec,
        scene=scene,
        frequency_hz=2.4e9,
        height_m=21.0,
        seed=9,
    )

    assert result.shape == (128, 128)
    assert result[0, 0] == np.float32(10 * np.log10(2e-9 * 1_000))
    assert result[-1, 0] == np.float32(10 * np.log10(4e-9 * 1_000))
    assert captured["height_m"] == 21.0
    assert captured["frequency_hz"] == 2.4e9
    assert captured["seed"] == 9
