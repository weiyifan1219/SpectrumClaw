from __future__ import annotations

import numpy as np


class ConstantSionnaProvider:
    provider_name = "sionna_rt"

    def generate_total_rss(self, *, spec, scene, frequency_hz, height_m, seed):
        return np.full((spec.rows, spec.columns), -75.0, dtype=np.float32)


def test_validate_dataset_reports_shape_ranges_and_counts(tmp_path):
    from uav_rem_active_mapping.dataset_builder import build_dataset
    from uav_rem_active_mapping.validation import validate_dataset

    build_dataset(
        output_dir=tmp_path,
        provider=ConstantSionnaProvider(),
        scene_seeds=[5],
        split="pilot",
    )
    report = validate_dataset(tmp_path)

    assert report["ok"] is True
    assert report["sample_count"] == 1
    assert report["shape"] == [1, 5, 128, 128]
    assert report["rss_min_dbm"] == -75.0
    assert report["rss_max_dbm"] == -75.0
    assert report["providers"] == ["sionna_rt"]


def test_config_loader_rejects_non_sionna_provider(tmp_path):
    from uav_rem_active_mapping.config import load_dataset_config

    path = tmp_path / "bad.yaml"
    path.write_text("provider: analytic\n", encoding="utf-8")

    try:
        load_dataset_config(path)
    except ValueError as exc:
        assert "provider 必须是 sionna" in str(exc)
    else:
        raise AssertionError("non-Sionna config should fail")


def test_config_loader_resolves_relative_artifacts_from_package_root(tmp_path):
    from uav_rem_active_mapping.config import load_dataset_config

    package_root = tmp_path / "research_package"
    config_dir = package_root / "configs" / "dataset"
    config_dir.mkdir(parents=True)
    path = config_dir / "pilot.yaml"
    path.write_text(
        """provider: sionna
dataset:
  scene_seeds: [1]
  output: artifacts/datasets/pilot
ray_tracing:
  asset_dir: artifacts/assets/pilot
""",
        encoding="utf-8",
    )

    config = load_dataset_config(path)

    assert config.output_dir == package_root / "artifacts" / "datasets" / "pilot"
    assert config.asset_dir == package_root / "artifacts" / "assets" / "pilot"
