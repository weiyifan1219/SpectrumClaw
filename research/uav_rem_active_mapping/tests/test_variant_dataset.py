from __future__ import annotations

import numpy as np


class ConstantSionnaProvider:
    provider_name = "sionna_rt"

    def generate_total_rss(self, *, spec, scene, frequency_hz, height_m, seed):
        return np.full((spec.rows, spec.columns), -68.0, dtype=np.float32)

    def rt_metadata(self):
        return {"engine": "sionna_rt", "test_provider": True}


def test_variant_dataset_writes_paired_assets_and_scene_bound_npz(tmp_path):
    from uav_rem_active_mapping.variant_dataset import build_layout_dataset

    result = build_layout_dataset(
        output_root=tmp_path / "data",
        asset_root=tmp_path / "assets",
        provider=ConstantSionnaProvider(),
        layout_index=1,
        split="train",
        source_seeds=[101, 102],
    )

    assert result["sample_count"] == 2
    assert result["scene_id"] == "urban_layout_01"
    assert result["gazebo_world"].is_file()
    assert result["sionna_xml"].is_file()
    assert (tmp_path / "data" / "urban_layout_01" / "manifest.json").is_file()


def test_variant_dataset_appends_new_source_seeds_without_losing_prior_manifest_entries(tmp_path):
    from uav_rem_active_mapping.variant_dataset import build_layout_dataset

    kwargs = {
        "output_root": tmp_path / "data",
        "asset_root": tmp_path / "assets",
        "provider": ConstantSionnaProvider(),
        "layout_index": 1,
        "split": "train",
    }
    build_layout_dataset(source_seeds=[101], **kwargs)
    result = build_layout_dataset(source_seeds=[102], **kwargs)

    assert result["sample_count"] == 2
    assert {item["seed"] for item in result["samples"]} == {101, 102}


def test_variant_dataset_recovers_npz_when_worker_stopped_before_manifest(tmp_path):
    from uav_rem_active_mapping.variant_dataset import build_layout_dataset

    kwargs = {
        "output_root": tmp_path / "data",
        "asset_root": tmp_path / "assets",
        "provider": ConstantSionnaProvider(),
        "layout_index": 1,
        "split": "train",
    }
    build_layout_dataset(source_seeds=[101], **kwargs)
    first_path = tmp_path / "data" / "urban_layout_01" / "train" / "urban_layout_01-00000101.npz"
    original = first_path.read_bytes()
    (tmp_path / "data" / "urban_layout_01" / "manifest.json").unlink()

    result = build_layout_dataset(source_seeds=[101, 102], **kwargs)

    assert result["sample_count"] == 2
    assert first_path.read_bytes() == original


def test_multiband_variant_keeps_frequency_height_axis_contract(tmp_path):
    from uav_rem_active_mapping.contracts import DatasetSpec
    from uav_rem_active_mapping.variant_dataset import build_layout_dataset

    frequencies = (1.4e9, 1.8e9, 2.4e9, 3.5e9, 5.8e9)
    spec = DatasetSpec(frequencies_hz=frequencies)
    result = build_layout_dataset(
        output_root=tmp_path / "data",
        asset_root=tmp_path / "assets",
        provider=ConstantSionnaProvider(),
        layout_index=35,
        split="pretrain",
        source_seeds=[101],
        spec=spec,
    )

    assert result["shape"] == [5, 5, 128, 128]
    assert result["frequencies_hz"] == list(frequencies)
    with np.load(tmp_path / "data" / "urban_layout_35" / "pretrain" / "urban_layout_35-00000101.npz") as sample:
        assert sample["rss_dbm"].shape == (5, 5, 128, 128)
