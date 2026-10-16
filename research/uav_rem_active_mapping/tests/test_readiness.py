"""Regression checks for unattended production training."""
import json

import numpy as np
import pytest
import torch
from torch.utils.data import DataLoader

from test_single_height_training import _write_multiband_fixture
from uav_rem_active_mapping.training_data import MultiBandHeightDataset, compute_multiband_statistics


def dataset_fixture(tmp_path):
    root = _write_multiband_fixture(tmp_path / "data")
    frequencies = [1.4e9, 1.8e9, 2.4e9, 3.5e9, 5.8e9]
    stats = compute_multiband_statistics(roots=[root], split="pretrain", heights_m=[9, 13, 17, 21, 25], frequencies_hz=frequencies)
    return MultiBandHeightDataset(roots=[root], split="pretrain", heights_m=[13], frequencies_hz=frequencies,
                                 normalization=stats, sample_rates=[0.01], mask_modes=["random"], cache_in_memory=True)


def test_persistent_workers_receive_epoch_and_reproduce_masks(tmp_path):
    dataset = dataset_fixture(tmp_path)
    loader = DataLoader(dataset, batch_size=5, num_workers=2, persistent_workers=True)
    first = next(iter(loader))["observed_mask"]
    dataset.set_epoch(1)
    second = next(iter(loader))["observed_mask"]
    dataset.set_epoch(0)
    repeated = next(iter(loader))["observed_mask"]
    assert not torch.equal(first, second)
    assert torch.equal(first, repeated)


def test_astar_does_not_cut_building_corners():
    from uav_rem_active_mapping.planning import astar_grid
    with pytest.raises(RuntimeError):
        astar_grid([[True, False], [False, True]], (0, 0), (1, 1))


def test_missing_scalar_metadata_is_rejected():
    from test_dataset_contract import _valid_sample
    from uav_rem_active_mapping.contracts import DEFAULT_DATASET_SPEC, validate_sample
    sample = _valid_sample(DEFAULT_DATASET_SPEC)
    del sample["scene_config_json"]
    with pytest.raises(ValueError, match="scene_config_json"):
        validate_sample(sample)


def test_validation_rejects_duplicate_manifest_entries(tmp_path):
    from test_validation import ConstantSionnaProvider
    from uav_rem_active_mapping.dataset_builder import build_dataset
    from uav_rem_active_mapping.validation import validate_dataset
    build_dataset(output_dir=tmp_path, provider=ConstantSionnaProvider(), scene_seeds=[5], split="pilot")
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["samples"] *= 2
    manifest["sample_count"] = 2
    path.unlink()
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="重复"):
        validate_dataset(tmp_path)


def test_rt_rejects_nonfinite_even_with_injected_solver(tmp_path):
    from uav_rem_active_mapping.sionna_provider import SionnaRadioMapProvider
    from uav_rem_active_mapping.scenes import urban_block_scene
    from uav_rem_active_mapping.contracts import DEFAULT_DATASET_SPEC
    scene = urban_block_scene(seed=5)
    provider = SionnaRadioMapProvider(asset_dir=tmp_path, solve_plane=lambda **kw: np.full((len(scene.transmitters),128,128), np.nan))
    with pytest.raises(ValueError, match="非有限"):
        provider.generate_total_rss(spec=DEFAULT_DATASET_SPEC, scene=scene, frequency_hz=2.4e9, height_m=13, seed=5)


def test_rt_retry_changes_only_ray_seed_and_records_it(tmp_path):
    from uav_rem_active_mapping.sionna_provider import SionnaRadioMapProvider
    from uav_rem_active_mapping.scenes import urban_block_scene
    from uav_rem_active_mapping.contracts import DEFAULT_DATASET_SPEC
    scene = urban_block_scene(seed=5)
    calls = []
    def solve(**kwargs):
        calls.append(kwargs)
        return np.full((len(scene.transmitters),128,128), np.nan if len(calls) == 1 else 1e-9)
    provider = SionnaRadioMapProvider(asset_dir=tmp_path, solve_plane=solve)
    with pytest.warns(RuntimeWarning):
        plane = provider.generate_total_rss(spec=DEFAULT_DATASET_SPEC, scene=scene, frequency_hz=2.4e9, height_m=13, seed=5)
    assert np.isfinite(plane).all()
    assert provider.last_plane_seed == 6 and provider.last_plane_attempts == 2
    assert calls[0]["scene"] is calls[1]["scene"]


def test_multiband_training_resume_and_finetune_reuse_statistics(tmp_path):
    import copy
    from uav_rem_active_mapping.training import run_training
    roots = {s: _write_multiband_fixture(tmp_path / s, split=s) for s in ("pretrain", "validation", "test", "finetune")}
    config = {
        "stage": "pretrain",
        "task": {"frequencies_hz": [1.4e9, 1.8e9, 2.4e9, 3.5e9, 5.8e9], "pretrain_heights_m": [9,13,17,21,25], "finetune_height_m": 13},
        "model": {"base_channels": 8, "transformer_depth": 1, "attention_heads": 2, "sampling_depth": 1, "dropout": 0, "frequency_height_conditioning": True},
        "data": {"train_roots": [str(roots["pretrain"])], "train_split": "pretrain", "validation_roots": [str(roots["validation"])], "test_roots": [str(roots["test"])],
                 "sample_rate_range": [0.01,0.25], "mask_modes": ["random"], "cache_in_memory": True},
        "optimization": {"epochs": 1, "batch_size": 5, "learning_rate": 1e-4, "weight_decay": 0, "num_workers": 2, "persistent_workers": True, "resume": True, "save_last_every": 1},
        "runtime": {"seed": 42, "amp": False},
        "output": {"checkpoint_dir": str(tmp_path / "checkpoints"), "report": str(tmp_path / "pretrain.json"), "log": str(tmp_path / "pretrain.jsonl")},
    }
    report = run_training(config, package_root=tmp_path, device=torch.device("cpu"))
    assert report["history"][0]["samples_seen"] == 25
    assert report["optimizer_steps"] == 5
    resumed = run_training(config, package_root=tmp_path, device=torch.device("cpu"))
    assert resumed["optimizer_steps"] == 5
    assert resumed["history"] == report["history"]
    fine = copy.deepcopy(config)
    fine["stage"] = "finetune"
    fine["data"].update(train_roots=[str(roots["finetune"])], train_split="finetune", sample_rate_range=[0,0.05])
    fine["optimization"]["initial_checkpoint"] = str(tmp_path / "checkpoints/best.pt")
    fine["output"] = {"checkpoint_dir": str(tmp_path / "fine"), "report": str(tmp_path / "finetune.json"), "log": str(tmp_path / "fine.jsonl")}
    result = run_training(fine, package_root=tmp_path, device=torch.device("cpu"))
    assert result["normalization"] == report["normalization"]
    assert result["history"][0]["samples_seen"] == 5


def test_policy_stop_only_has_finite_backward():
    from uav_rem_active_mapping.planning import CandidateAttentionPolicy
    model = CandidateAttentionPolicy(hidden_channels=16, attention_heads=2, attention_depth=1)
    logits, value = model(torch.zeros(1,8,8,8), torch.tensor([[[0,0],[1,1]]]), torch.ones(1,2), torch.tensor([[False,False,True]]))
    loss = torch.distributions.Categorical(logits=logits).log_prob(torch.tensor([2])).sum() + value.sum()
    loss.backward()
    assert torch.isfinite(value).all()
    assert all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None)
