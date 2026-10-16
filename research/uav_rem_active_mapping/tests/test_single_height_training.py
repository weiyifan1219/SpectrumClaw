from __future__ import annotations

import json

import numpy as np


def _write_training_fixture(root, split="train"):
    rows = columns = 128
    heights = np.asarray([9.0, 13.0, 17.0, 21.0, 25.0], dtype=np.float32)
    rss = np.stack(
        [np.full((rows, columns), -90.0 + index * 5.0, dtype=np.float32) for index in range(5)],
        axis=0,
    )[None, ...]
    checkerboard = (np.indices((rows, columns)).sum(axis=0) % 2).astype(np.float32)
    rss[0, 1] = -86.0 + 2.0 * checkerboard
    building_height = np.zeros((rows, columns), dtype=np.float32)
    building_height[20:40, 30:50] = 18.0
    building_height[60:70, 70:80] = 8.0
    valid = np.stack([(building_height < height).astype(np.uint8) for height in heights], axis=0)
    flyable = valid.copy()
    sample = {
        "sample_id": np.asarray("fixture-0001"),
        "rss_dbm": rss,
        "frequencies_hz": np.asarray([2.4e9], dtype=np.float64),
        "heights_m": heights,
        "bounds_enu_m": np.asarray([-60.0, 60.0, -60.0, 60.0], dtype=np.float32),
        "building_height_m": building_height,
        "valid_rx_mask": valid,
        "flyable_mask": flyable,
        "tx_positions_m": np.asarray([[45.0, 0.0, 20.0]], dtype=np.float32),
        "tx_powers_dbm": np.asarray([[20.0]], dtype=np.float32),
    }
    path = root / split / "fixture-0001.npz"
    path.parent.mkdir(parents=True)
    np.savez_compressed(path, **sample)
    (root / "manifest.json").write_text(json.dumps({
        "sample_count": 1,
        "samples": [{"path": f"{split}/fixture-0001.npz", "sample_id": "fixture-0001", "split": split}],
    }), encoding="utf-8")
    return root


def _write_multiband_fixture(root, split="pretrain"):
    rows = columns = 128
    heights = np.asarray([9.0, 13.0, 17.0, 21.0, 25.0], dtype=np.float32)
    frequencies = np.asarray([1.4e9, 1.8e9, 2.4e9, 3.5e9, 5.8e9], dtype=np.float64)
    rss = np.empty((5, 5, rows, columns), dtype=np.float32)
    for frequency_index in range(5):
        for height_index in range(5):
            rss[frequency_index, height_index] = -95.0 + 5.0 * frequency_index + height_index
    building_height = np.zeros((rows, columns), dtype=np.float32)
    building_height[20:40, 30:50] = 18.0
    valid = np.stack([(building_height < height).astype(np.uint8) for height in heights])
    flyable = valid.copy()
    path = root / split / "multiband-0001.npz"
    path.parent.mkdir(parents=True)
    np.savez_compressed(
        path,
        rss_dbm=rss,
        frequencies_hz=frequencies,
        heights_m=heights,
        bounds_enu_m=np.asarray([-60.0, 60.0, -60.0, 60.0], dtype=np.float32),
        building_height_m=building_height,
        valid_rx_mask=valid,
        flyable_mask=flyable,
        tx_positions_m=np.asarray([[45.0, 0.0, 20.0]], dtype=np.float32),
        tx_powers_dbm=np.full((1, 5), 20.0, dtype=np.float32),
    )
    (root / "manifest.json").write_text(json.dumps({
        "samples": [{"path": f"{split}/multiband-0001.npz", "sample_id": "multiband-0001", "split": split}],
    }), encoding="utf-8")
    return root


def test_dataset_extracts_13m_and_samples_only_flyable_cells(tmp_path):
    from uav_rem_active_mapping.training_data import SingleHeightDataset

    dataset = SingleHeightDataset(
        roots=[_write_training_fixture(tmp_path / "data")],
        split="train",
        height_m=13.0,
        sample_rates=(0.01,),
        mask_modes=("random",),
        rss_mean_dbm=-85.0,
        rss_std_db=10.0,
        seed=17,
    )
    item = dataset[0]

    assert item["features"].shape == (8, 128, 128)
    assert item["target_dbm"].shape == (1, 128, 128)
    assert set(np.unique(item["target_dbm"].numpy())) == {-86.0, -84.0}
    assert np.isclose(float(item["target_dbm"].mean()), -85.0)
    assert int(item["observed_mask"].sum()) == 164
    assert not np.any(
        (item["observed_mask"].numpy() == 1)
        & (item["flyable_mask"].numpy() == 0)
    )
    assert float(item["sample_rate"]) < 0.05
    assert item["height_m"].item() == 13.0
    observed_values = item["features"][0][item["observed_mask"][0] == 1].numpy()
    np.testing.assert_allclose(np.unique(observed_values), [-0.1, 0.1], atol=1e-6)
    assert item["valid_mask"][0, 65, 75].item() == 1.0
    assert item["features"][2, 65, 75].item() == 1.0
    assert item["features"][3, 65, 75].item() > 0.0


def test_shadow_and_emitter_auxiliary_targets_are_finite_and_bounded(tmp_path):
    from uav_rem_active_mapping.training_data import SingleHeightDataset

    dataset = SingleHeightDataset(
        roots=[_write_training_fixture(tmp_path / "data")],
        split="train",
        height_m=13.0,
        sample_rates=(0.02,),
        mask_modes=("random",),
        rss_mean_dbm=-85.0,
        rss_std_db=10.0,
        seed=19,
    )
    item = dataset[0]

    for key in ("shadow_target", "emitter_target"):
        value = item[key].numpy()
        assert value.shape == (1, 128, 128)
        assert np.all(np.isfinite(value))
        assert value.min() >= 0.0
        assert value.max() <= 1.0
    assert item["emitter_target"].max().item() > 0.9


def test_geotransunet_outputs_single_height_belief_and_preserves_observations():
    import torch

    from uav_rem_active_mapping.models.geotransunet import GeoTransUNet

    model = GeoTransUNet(base_channels=16, transformer_depth=1, attention_heads=4)
    features = torch.zeros(2, 8, 128, 128)
    features[:, 0] = 0.4
    features[:, 1, 10, 20] = 1.0
    outputs = model(features)

    assert outputs["mean_dbm"].shape == (2, 1, 128, 128)
    assert outputs["scale_db"].shape == (2, 1, 128, 128)
    assert outputs["shadow_probability"].shape == (2, 1, 128, 128)
    assert outputs["emitter_probability"].shape == (2, 1, 128, 128)
    assert outputs["shadow_logits"].shape == (2, 1, 128, 128)
    assert outputs["emitter_logits"].shape == (2, 1, 128, 128)
    assert torch.all(outputs["scale_db"] > 0)
    expected_observation = model.rss_mean_dbm.item() + model.rss_std_db.item() * 0.4
    assert torch.allclose(
        outputs["mean_dbm"][:, 0, 10, 20],
        torch.full((2,), expected_observation),
    )
    assert torch.allclose(outputs["scale_db"][:, 0, 10, 20], torch.full((2,), 0.5))


def test_frequency_height_conditioning_and_per_sample_denormalization():
    import torch

    from uav_rem_active_mapping.models.geotransunet import GeoTransUNet

    model = GeoTransUNet(
        base_channels=8,
        transformer_depth=1,
        attention_heads=2,
        sampling_depth=1,
        dropout=0.0,
        frequency_height_conditioning=True,
    ).eval()
    features = torch.zeros(2, 8, 128, 128)
    features[:, 0, 10, 20] = 0.5
    features[:, 1, 10, 20] = 1.0
    outputs = model(
        features,
        frequency_hz=torch.tensor([1.4e9, 5.8e9]),
        height_m=torch.tensor([9.0, 25.0]),
        rss_mean_dbm=torch.tensor([-80.0, -60.0]),
        rss_std_db=torch.tensor([10.0, 20.0]),
    )

    torch.testing.assert_close(outputs["mean_dbm"][:, 0, 10, 20], torch.tensor([-75.0, -50.0]))
    assert not torch.allclose(outputs["mean_dbm"][0], outputs["mean_dbm"][1])


def test_multiband_dataset_expands_every_frequency_height_pair(tmp_path):
    from uav_rem_active_mapping.training_data import MultiBandHeightDataset

    frequencies = [1.4e9, 1.8e9, 2.4e9, 3.5e9, 5.8e9]
    normalization = {
        "per_frequency": {
            str(int(frequency)): {"mean_dbm": -80.0, "std_db": 10.0}
            for frequency in frequencies
        }
    }
    dataset = MultiBandHeightDataset(
        roots=[_write_multiband_fixture(tmp_path / "data")],
        split="pretrain",
        heights_m=[9, 13, 17, 21, 25],
        frequencies_hz=frequencies,
        normalization=normalization,
        sample_rates=[0.01],
        mask_modes=["random"],
    )

    assert len(dataset) == 25
    assert dataset[0]["frequency_hz"].item() == 1.4e9
    assert dataset[0]["height_m"].item() == 9.0
    assert dataset[24]["frequency_hz"].item() == 5.8e9
    assert dataset[24]["height_m"].item() == 25.0
    assert dataset[0]["features"].shape == (8, 128, 128)


def test_sampling_pattern_encoder_injects_observed_values_into_global_tokens():
    import torch

    from uav_rem_active_mapping.models.geotransunet import SamplingPatternEncoder

    encoder = SamplingPatternEncoder(channels=32, attention_heads=4, depth=1, dropout=0.0)
    tokens = torch.zeros(1, 16 * 16, 32)
    position = torch.zeros_like(tokens)
    sparse = torch.zeros(1, 1, 128, 128)
    mask = torch.zeros_like(sparse)
    without_measurements = encoder(tokens, sparse, mask, position, grid_shape=(16, 16))
    sparse[:, :, 32, 48] = 1.5
    mask[:, :, 32, 48] = 1.0
    with_measurement = encoder(tokens, sparse, mask, position, grid_shape=(16, 16))

    assert without_measurements.shape == tokens.shape
    assert torch.all(torch.isfinite(with_measurement))
    assert not torch.allclose(without_measurements, with_measurement)


def test_rss_prediction_backpropagates_through_emitter_head():
    import torch

    from uav_rem_active_mapping.models.geotransunet import GeoTransUNet

    model = GeoTransUNet(
        base_channels=8,
        transformer_depth=1,
        attention_heads=2,
        sampling_depth=1,
        propagation_refinement=True,
    )
    features = torch.zeros(1, 8, 128, 128)
    outputs = model(features)
    outputs["mean_dbm"].mean().backward()

    gradient = model.emitter_head.weight.grad
    assert gradient is not None
    assert torch.count_nonzero(gradient).item() > 0


def test_five_percent_request_is_strictly_below_grid_budget(tmp_path):
    from uav_rem_active_mapping.training_data import SingleHeightDataset

    dataset = SingleHeightDataset(
        roots=[_write_training_fixture(tmp_path / "data")],
        split="train",
        height_m=13.0,
        sample_rates=(0.05,),
        mask_modes=("random",),
        rss_mean_dbm=-85.0,
        rss_std_db=1.0,
        seed=23,
    )
    item = dataset[0]

    assert int(item["observed_mask"].sum()) == 819
    assert float(item["sample_rate"]) < 0.05


def test_zero_measurement_initial_belief_is_supported(tmp_path):
    from uav_rem_active_mapping.training_data import SingleHeightDataset

    dataset = SingleHeightDataset(
        roots=[_write_training_fixture(tmp_path / "data")],
        split="train",
        height_m=13.0,
        sample_rates=(0.0,),
        mask_modes=("trajectory",),
        rss_mean_dbm=-85.0,
        rss_std_db=1.0,
        seed=29,
    )
    item = dataset[0]

    assert int(item["observed_mask"].sum()) == 0
    assert item["sample_rate"].item() == 0.0
    assert np.all(item["features"][0].numpy() == 0.0)


def test_trajectory_measurements_form_one_connected_path(tmp_path):
    from collections import deque

    from uav_rem_active_mapping.training_data import SingleHeightDataset

    dataset = SingleHeightDataset(
        roots=[_write_training_fixture(tmp_path / "data")],
        split="train",
        height_m=13.0,
        sample_rates=(0.01,),
        mask_modes=("trajectory",),
        rss_mean_dbm=-85.0,
        rss_std_db=1.0,
        seed=31,
    )
    mask = dataset[0]["observed_mask"][0].numpy().astype(bool)
    start = tuple(np.argwhere(mask)[0])
    visited = {start}
    queue = deque([start])
    while queue:
        row, column = queue.popleft()
        for delta_row in (-1, 0, 1):
            for delta_column in (-1, 0, 1):
                neighbour = (row + delta_row, column + delta_column)
                if (
                    neighbour not in visited
                    and 0 <= neighbour[0] < mask.shape[0]
                    and 0 <= neighbour[1] < mask.shape[1]
                    and mask[neighbour]
                ):
                    visited.add(neighbour)
                    queue.append(neighbour)
    assert len(visited) == int(mask.sum())


def test_shadow_aware_loss_ignores_building_interior_and_backpropagates():
    import torch

    from uav_rem_active_mapping.losses import ShadowAwareLoss

    mean = torch.full((1, 1, 8, 8), -70.0, requires_grad=True)
    outputs = {
        "mean_dbm": mean,
        "scale_db": torch.full((1, 1, 8, 8), 3.0, requires_grad=True),
        "shadow_logits": torch.zeros(1, 1, 8, 8, requires_grad=True),
        "emitter_logits": torch.zeros(1, 1, 8, 8, requires_grad=True),
        "shadow_probability": torch.full((1, 1, 8, 8), 0.5, requires_grad=True),
        "emitter_probability": torch.full((1, 1, 8, 8), 0.5, requires_grad=True),
    }
    batch = {
        "target_dbm": torch.full((1, 1, 8, 8), -80.0),
        "valid_mask": torch.ones(1, 1, 8, 8),
        "observed_mask": torch.zeros(1, 1, 8, 8),
        "shadow_target": torch.zeros(1, 1, 8, 8),
        "emitter_target": torch.zeros(1, 1, 8, 8),
    }
    batch["valid_mask"][:, :, :2, :2] = 0
    batch["target_dbm"][:, :, :2, :2] = 1_000.0

    result = ShadowAwareLoss(rss_std_db=20.0, mse_weight=0.2)(outputs, batch)
    result["loss"].backward()

    assert torch.isfinite(result["loss"])
    assert result["loss"].item() < 1.0
    assert result["mse_loss"].item() > 0.0
    assert mean.grad is not None
    assert torch.all(mean.grad[:, :, :2, :2] == 0)


def test_rss_standardization_has_zero_mean_and_unit_variance():
    from uav_rem_active_mapping.training_data import standardize_rss

    values = np.asarray([-95.0, -80.0, -65.0, -50.0], dtype=np.float32)
    standardized = standardize_rss(values, mean_dbm=float(values.mean()), std_db=float(values.std()))

    assert abs(float(standardized.mean())) < 1e-6
    assert abs(float(standardized.std()) - 1.0) < 1e-6


def test_training_statistics_use_only_requested_split_height_and_valid_cells(tmp_path):
    from uav_rem_active_mapping.training_data import compute_rss_statistics

    root = _write_training_fixture(tmp_path / "data", split="train")
    statistics = compute_rss_statistics(
        roots=[root],
        split="train",
        height_m=13.0,
        frequency_hz=2.4e9,
    )

    assert statistics["mean_dbm"] == -85.0
    assert statistics["std_db"] == 1.0
    assert statistics["height_m"] == 13.0
    assert statistics["sample_count"] == 1


def test_memory_cached_dataset_does_not_reopen_npz(tmp_path):
    from uav_rem_active_mapping.training_data import SingleHeightDataset

    root = _write_training_fixture(tmp_path / "data", split="train")
    dataset = SingleHeightDataset(
        roots=[root],
        split="train",
        height_m=13.0,
        sample_rates=(0.01,),
        mask_modes=("trajectory",),
        rss_mean_dbm=-85.0,
        rss_std_db=1.0,
        seed=37,
        cache_in_memory=True,
    )
    (root / "train" / "fixture-0001.npz").unlink()

    item = dataset[0]

    assert item["target_dbm"].shape == (1, 128, 128)
    assert int(item["observed_mask"].sum()) == 164


def test_metrics_use_blind_valid_cells_and_report_shadow_error():
    import torch

    from uav_rem_active_mapping.metrics import reconstruction_metric_sums

    outputs = {
        "mean_dbm": torch.tensor([[[[-70.0, -70.0], [-80.0, -90.0]]]]),
        "scale_db": torch.full((1, 1, 2, 2), 5.0),
    }
    batch = {
        "target_dbm": torch.tensor([[[[-80.0, -70.0], [-80.0, 500.0]]]]),
        "valid_mask": torch.tensor([[[[1.0, 1.0], [1.0, 0.0]]]]),
        "observed_mask": torch.tensor([[[[0.0, 1.0], [0.0, 0.0]]]]),
        "shadow_target": torch.tensor([[[[1.0, 0.0], [0.0, 0.0]]]]),
    }

    sums = reconstruction_metric_sums(outputs, batch)

    assert sums["count"].item() == 2
    assert sums["squared_error"].item() == 100.0
    assert sums["absolute_error"].item() == 10.0
    assert sums["shadow_count"].item() == 1
    assert sums["shadow_squared_error"].item() == 100.0


def test_formal_training_config_is_multiband_multiheight_and_has_no_lite_variant():
    from pathlib import Path

    import yaml

    from uav_rem_active_mapping.training import resolve_stage_config

    package_root = Path(__file__).parents[1]
    formal = yaml.safe_load((package_root / "configs" / "model" / "geotransunet.yaml").read_text(encoding="utf-8"))
    config = resolve_stage_config(formal, "pretrain")

    assert config["task"]["finetune_height_m"] == 13.0
    assert config["task"]["pretrain_heights_m"] == [9.0, 13.0, 17.0, 21.0, 25.0]
    assert config["task"]["frequencies_hz"] == [1.4e9, 1.8e9, 2.4e9, 3.5e9, 5.8e9]
    assert config["data"]["sample_rate_range"] == [0.01, 0.25]
    finetune = resolve_stage_config(formal, "finetune")
    assert finetune["data"]["sample_rate_range"] == [0.0, 0.05]
    assert finetune["data"]["mask_modes"].count("trajectory") / len(finetune["data"]["mask_modes"]) >= 0.8
    assert not (package_root / "configs" / "model" / "transunet_lite.yaml").exists()


def test_pretrain_and_finetune_use_disjoint_geometry_and_outputs():
    from pathlib import Path

    import yaml

    from uav_rem_active_mapping.training import resolve_stage_config

    package_root = Path(__file__).parents[1]
    formal = yaml.safe_load((package_root / "configs" / "model" / "geotransunet.yaml").read_text(encoding="utf-8"))
    pretrain = resolve_stage_config(formal, "pretrain")
    finetune = resolve_stage_config(formal, "finetune")

    assert len(pretrain["data"]["train_roots"]) == 24
    assert len(finetune["data"]["train_roots"]) == 6
    assert set(pretrain["data"]["train_roots"]).isdisjoint(finetune["data"]["train_roots"])
    assert finetune["optimization"]["initial_checkpoint"] == "checkpoints/reconstructor/pretrain/best.pt"
    assert pretrain["output"]["checkpoint_dir"] != finetune["output"]["checkpoint_dir"]


def test_training_loop_writes_checkpoint_and_ground_truth_metrics(tmp_path):
    import torch

    from uav_rem_active_mapping.training import run_training

    train_root = _write_training_fixture(tmp_path / "train_data", split="train")
    validation_root = _write_training_fixture(tmp_path / "validation_data", split="validation")
    test_root = _write_training_fixture(tmp_path / "test_data", split="test")
    config = {
        "task": {"height_m": 13.0, "frequency_hz": 2.4e9},
        "model": {"base_channels": 8, "transformer_depth": 1, "attention_heads": 2, "dropout": 0.0},
        "data": {
            "train_roots": [str(train_root)],
            "validation_roots": [str(validation_root)],
            "test_roots": [str(test_root)],
            "sample_rates": [0.01],
            "mask_modes": ["random"],
        },
        "optimization": {
            "epochs": 1,
            "batch_size": 1,
            "learning_rate": 1e-3,
            "weight_decay": 0.0,
            "num_workers": 0,
            "max_train_steps": 1,
        },
        "runtime": {"seed": 3, "amp": False},
        "normalization": {
            "mean_dbm": -80.0,
            "std_db": 5.0,
            "height_m": 13.0,
            "frequency_hz": 2.4e9,
            "sample_count": 1,
            "valid_cell_count": 15984,
        },
        "output": {
            "checkpoint_dir": str(tmp_path / "checkpoints"),
            "report": str(tmp_path / "report.json"),
        },
    }

    report = run_training(config, package_root=tmp_path, device=torch.device("cpu"))

    assert (tmp_path / "checkpoints" / "best.pt").is_file()
    assert (tmp_path / "checkpoints" / "last.pt").is_file()
    assert (tmp_path / "report.json").is_file()
    assert report["task"]["height_m"] == 13.0
    assert report["normalization"]["mean_dbm"] == -80.0
    assert report["normalization"]["std_db"] == 5.0
    assert report["validation"]["rmse_db"] >= 0.0
    assert report["test"]["rmse_db"] >= 0.0
    assert report["optimizer_steps"] == 1


def test_gpu_selection_respects_cuda_visible_device_count():
    from uav_rem_active_mapping.training import usable_gpu_ids

    assert usable_gpu_ids([0, 1], visible_device_count=1) == [0]
    assert usable_gpu_ids([0, 1], visible_device_count=2) == [0, 1]


def test_initial_checkpoint_allows_only_new_refinement_parameters(tmp_path):
    import torch

    from uav_rem_active_mapping.models.geotransunet import GeoTransUNet
    from uav_rem_active_mapping.training import load_initial_weights

    old_model = GeoTransUNet(base_channels=8, transformer_depth=1, attention_heads=2, sampling_depth=1)
    checkpoint = tmp_path / "old.pt"
    torch.save({"model": old_model.state_dict()}, checkpoint)
    new_model = GeoTransUNet(
        base_channels=8,
        transformer_depth=1,
        attention_heads=2,
        sampling_depth=1,
        propagation_refinement=True,
    )

    result = load_initial_weights(new_model, checkpoint, device=torch.device("cpu"))

    assert result["unexpected_keys"] == []
    assert result["missing_keys"]
    assert all(key.startswith("propagation_refiner.") for key in result["missing_keys"])
    torch.testing.assert_close(new_model.mean_head.weight, old_model.mean_head.weight)


def test_atomic_checkpoint_replaces_existing_file(tmp_path):
    import torch

    from uav_rem_active_mapping.training import atomic_torch_save

    path = tmp_path / "checkpoint.pt"
    atomic_torch_save({"value": torch.tensor(1)}, path)
    atomic_torch_save({"value": torch.tensor(2)}, path)

    loaded = torch.load(path, map_location="cpu", weights_only=False)
    assert loaded["value"].item() == 2
    assert not path.with_suffix(".pt.tmp").exists()
