from __future__ import annotations

import json

import numpy as np


class ConstantSionnaProvider:
    provider_name = "sionna_rt"

    def generate_total_rss(self, *, spec, scene, frequency_hz, height_m, seed):
        return np.full((spec.rows, spec.columns), -70.0 - height_m * 0.1, dtype=np.float32)


def test_builder_writes_valid_npz_and_manifest(tmp_path):
    from uav_rem_active_mapping.dataset_builder import build_dataset

    result = build_dataset(
        output_dir=tmp_path,
        provider=ConstantSionnaProvider(),
        scene_seeds=[101, 102],
        split="pilot",
    )

    assert result["sample_count"] == 2
    assert (tmp_path / "pilot" / "urban-block-00000101.npz").is_file()
    assert (tmp_path / "pilot" / "urban-block-00000102.npz").is_file()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "spectrumclaw.uav-rem.fzhw.v4"
    assert manifest["provider"] == "sionna_rt"
    assert manifest["shape"] == [1, 5, 128, 128]
    assert [item["seed"] for item in manifest["samples"]] == [101, 102]
