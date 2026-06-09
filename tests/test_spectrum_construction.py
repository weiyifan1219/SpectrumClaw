"""Tests for the Spectrum Construction Gudmundson preview API."""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_gudmundson_preview_returns_multi_resolution_maps():
    from backend.skills.spectrum_construction.generator import build_multi_resolution_preview

    result = build_multi_resolution_preview(
        seed=7,
        resolutions=[32, 64],
        mask_ratio=0.75,
    )

    assert result["mask_ratio"] == 0.75
    assert result["mask_unit"] == "vit_patch"
    assert result["model_variant"] == "pretrain"
    assert result["checkpoint_status"] == "inference_disabled"
    assert [item["resolution"] for item in result["maps"]] == [32, 64]

    for item in result["maps"]:
        resolution = item["resolution"]
        patch_size = 2 if resolution == 32 else 4
        original = item["original"]
        masked = item["masked"]
        observed_mask = item["observed_mask"]

        assert item["patch_size"] == patch_size
        assert item["patch_grid"] == [16, 16]
        assert item["mask_unit"] == "vit_patch"
        assert item["inference_status"] == "inference_disabled"
        assert item["reconstruction"] is None
        assert item["rmse"] is None
        assert len(original) == resolution
        assert len(original[0]) == resolution
        assert len(masked) == resolution
        assert len(masked[0]) == resolution
        assert len(observed_mask) == resolution
        assert len(observed_mask[0]) == resolution
        assert len(item["source_positions"]) == 2
        assert item["metrics"]["min_dbm"] <= item["metrics"]["mean_dbm"] <= item["metrics"]["max_dbm"]

        visible = sum(sum(row) for row in observed_mask)
        total = resolution * resolution
        assert visible / total == 0.25

        visible_patches = 0
        for y in range(0, resolution, patch_size):
            for x in range(0, resolution, patch_size):
                block_values = {
                    observed_mask[row][col]
                    for row in range(y, y + patch_size)
                    for col in range(x, x + patch_size)
                }
                assert len(block_values) == 1
                visible_patches += next(iter(block_values))

        assert visible_patches == 64


def test_spectrum_construction_api_generate_defaults():
    from backend.api.spectrum_construction import (
        SpectrumConstructionRequest,
        handle_generate,
    )

    data = handle_generate(SpectrumConstructionRequest(seed=3))

    assert data["status"] == "ok"
    assert data["mask_ratio"] == 0.75
    assert data["mask_unit"] == "vit_patch"
    assert data["model_variant"] == "pretrain"
    assert data["checkpoint_status"] == "inference_disabled"
    assert [item["resolution"] for item in data["maps"]] == [32, 64, 128, 224]
    assert all(item["patch_grid"] == [16, 16] for item in data["maps"])


def test_uav_rem_overview_reads_existing_results(tmp_path, monkeypatch):
    from backend.api.spectrum_construction import (
        UavRemOverviewRequest,
        handle_uav_rem_overview,
    )

    root = tmp_path / "Agent_UAV_REM"
    (root / "results" / "abr").mkdir(parents=True)
    (root / "results" / "baselines" / "knn").mkdir(parents=True)
    (root / "results").mkdir(exist_ok=True)
    (root / "docs").mkdir()

    (root / "results" / "final_comparison.csv").write_text(
        "Method,0.0010,0.0050\n"
        "ABR,4.54,3.07\n"
        "KNN,6.65,6.22\n",
        encoding="utf-8",
    )
    (root / "results" / "abr" / "results.csv").write_text(
        "scene,policy,rmse_0.0010,rmse_0.0050,auc,n_samples,elapsed\n"
        "148,abr,4.5,3.0,0.1,64,2.0\n",
        encoding="utf-8",
    )
    (root / "docs" / "ALGORITHM_README.md").write_text(
        "# UAV-Agent REM Construction\n"
        "Build a Radio Environment Map using sparse UAV measurements.\n",
        encoding="utf-8",
    )

    gt = np.linspace(-90, -60, 5 * 4 * 4, dtype=np.float32).reshape(5, 4, 4)
    pred = gt + 1.5
    valid = np.zeros((5, 4, 4), dtype=np.float32)
    valid[2, 1, 1] = 1
    sampled = np.where(valid == 1, gt, -100).astype(np.float32)
    np.savez(
        root / "results" / "abr" / "scene_0148_abr.npz",
        gt_map=gt,
        sampled_map=sampled,
        valid_mask=valid,
        pred_map=pred,
        building_map=np.zeros_like(gt),
        path_coords=np.array([[2, 1, 1], [2, 2, 2]], dtype=np.int16),
        scene_id=np.array(148, dtype=np.int32),
        rmse=np.array(1.5, dtype=np.float32),
    )

    monkeypatch.setenv("SPECTRUMCLAW_AGENT_UAV_REM_ROOT", str(root))
    data = handle_uav_rem_overview(
        UavRemOverviewRequest(scene_id=148, height_layer=2, method="abr")
    )

    assert data["status"] == "ok"
    assert data["source"]["available"] is True
    assert data["comparison"]["rates"] == [0.001, 0.005]
    assert data["comparison"]["methods"][0]["method"] == "ABR"
    assert data["scene"]["scene_id"] == 148
    assert data["scene"]["height_layer"] == 2
    assert data["scene"]["rmse"] == 1.5
    assert len(data["scene"]["maps"]["ground_truth"]) == 4
    assert len(data["scene"]["path_points"]) == 2
