from __future__ import annotations

import json
import copy
import hashlib
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch.nn.utils import clip_grad_norm_
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader

from .losses import ShadowAwareLoss
from .data_io import durable_replace, atomic_write_text
from .metrics import finalize_metric_sums, reconstruction_metric_sums
from .models import GeoTransUNet
from .training_data import (
    MultiBandHeightDataset,
    SingleHeightDataset,
    compute_multiband_statistics,
    compute_rss_statistics,
)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def resolve_stage_config(config: dict[str, Any], stage: str) -> dict[str, Any]:
    """Resolve one explicit training stage from the single formal config."""
    stages = config.get("stages")
    if not isinstance(stages, dict) or stage not in stages:
        available = ", ".join(sorted(stages or {}))
        raise ValueError(f"未知训练阶段 {stage!r}; 可选阶段: {available}")
    base = {key: value for key, value in config.items() if key != "stages"}
    resolved = _deep_merge(base, stages[stage])
    resolved["stage"] = stage
    return resolved


def usable_gpu_ids(requested: list[int], *, visible_device_count: int) -> list[int]:
    return [index for index in requested if 0 <= index < int(visible_device_count)]


def load_initial_weights(
    model: torch.nn.Module,
    checkpoint: str | Path,
    *,
    device: torch.device,
) -> dict[str, list[str]]:
    state = torch.load(Path(checkpoint), map_location="cpu", weights_only=False)
    incompatible = model.load_state_dict(state["model"], strict=False)
    return {
        "missing_keys": list(incompatible.missing_keys),
        "unexpected_keys": list(incompatible.unexpected_keys),
    }


def atomic_torch_save(payload: Any, path: str | Path) -> None:
    destination = Path(path)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    torch.save(payload, temporary)
    durable_replace(temporary, destination)


def _resolve(package_root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (package_root / path).resolve()


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _make_dataset(
    config: dict[str, Any],
    package_root: Path,
    *,
    split: str,
    normalization: dict[str, float | int],
) -> SingleHeightDataset | MultiBandHeightDataset:
    data_config = config["data"]
    root_key = f"{split}_roots"
    maximum_key = f"max_{split}_samples"
    actual_split = str(data_config.get(f"{split}_split", split))
    if "frequencies_hz" in config["task"]:
        heights = (
            config["task"]["pretrain_heights_m"]
            if config.get("stage") == "pretrain"
            else [config["task"]["finetune_height_m"]]
        )
        return MultiBandHeightDataset(
            roots=[_resolve(package_root, value) for value in data_config[root_key]],
            split=actual_split,
            heights_m=heights,
            frequencies_hz=config["task"]["frequencies_hz"],
            normalization=normalization,
            sample_rates=(
                None
                if "sample_rates" not in data_config
                else tuple(float(value) for value in data_config["sample_rates"])
            ),
            sample_rate_range=(
                None
                if "sample_rate_range" not in data_config
                else tuple(float(value) for value in data_config["sample_rate_range"])
            ),
            mask_modes=tuple(str(value) for value in data_config["mask_modes"]),
            seed=int(config["runtime"]["seed"]) + (0 if split == "train" else 100_000),
            max_samples=data_config.get(maximum_key),
            cache_in_memory=bool(data_config.get("cache_in_memory", False)),
            cache_workers=int(data_config.get("cache_workers", 8)),
        )
    return SingleHeightDataset(
        roots=[_resolve(package_root, value) for value in data_config[root_key]],
        split=actual_split,
        height_m=float(config["task"]["height_m"]),
        frequency_hz=float(config["task"]["frequency_hz"]),
        sample_rates=(
            None
            if "sample_rates" not in data_config
            else tuple(float(value) for value in data_config["sample_rates"])
        ),
        sample_rate_range=(
            None
            if "sample_rate_range" not in data_config
            else tuple(float(value) for value in data_config["sample_rate_range"])
        ),
        mask_modes=tuple(str(value) for value in data_config["mask_modes"]),
        rss_mean_dbm=float(normalization["mean_dbm"]),
        rss_std_db=float(normalization["std_db"]),
        seed=int(config["runtime"]["seed"]) + (0 if split == "train" else 100_000),
        max_samples=data_config.get(maximum_key),
        cache_in_memory=bool(data_config.get("cache_in_memory", False)),
        cache_workers=int(data_config.get("cache_workers", 8)),
    )


@torch.no_grad()
def _validate(
    model: torch.nn.Module,
    loader: DataLoader,
    device: torch.device,
    *,
    amp: bool,
    amp_dtype: torch.dtype,
    grouped: bool = False,
) -> dict[str, Any]:
    model.eval()
    totals: dict[str, float] = {}
    groups: dict[str, dict[str, float]] = {}
    for batch in loader:
        tensor_batch = {key: value.to(device, non_blocking=True) for key, value in batch.items() if torch.is_tensor(value)}
        with torch.amp.autocast(device_type=device.type, enabled=amp, dtype=amp_dtype):
            outputs = model(
                tensor_batch["features"],
                frequency_hz=tensor_batch.get("frequency_hz"),
                height_m=tensor_batch.get("height_m"),
                rss_mean_dbm=tensor_batch.get("rss_mean_dbm"),
                rss_std_db=tensor_batch.get("rss_std_db"),
            )
        if not torch.isfinite(outputs["mean_dbm"]).all() or not torch.isfinite(outputs["scale_db"]).all():
            raise FloatingPointError("评估预测包含非有限值")
        for key, value in reconstruction_metric_sums(outputs, tensor_batch).items():
            totals[key] = totals.get(key, 0.0) + float(value.detach().cpu())
        if grouped:
            conditions = torch.stack((tensor_batch["frequency_hz"], tensor_batch["height_m"]), dim=1)
            for condition in torch.unique(conditions, dim=0):
                select = (conditions == condition).all(dim=1)
                name = f"{int(condition[0])}Hz/{float(condition[1]):g}m"
                sums = reconstruction_metric_sums({k: v[select] for k, v in outputs.items()}, {k: v[select] for k, v in tensor_batch.items()})
                group = groups.setdefault(name, {})
                for key, value in sums.items():
                    group[key] = group.get(key, 0.0) + float(value.detach().cpu())
    result = finalize_metric_sums(totals)
    if grouped:
        result["by_frequency_height"] = {name: finalize_metric_sums(sums) for name, sums in groups.items()}
    return result


def run_training(
    config: dict[str, Any],
    *,
    package_root: str | Path,
    device: torch.device | None = None,
) -> dict[str, Any]:
    package_root = Path(package_root).resolve()
    seed = int(config["runtime"]["seed"])
    _seed_everything(seed)
    device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
    optimization = config["optimization"]
    checkpoint_dir = _resolve(package_root, config["output"]["checkpoint_dir"])
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    resume_state = None
    if optimization.get("resume", False) and (checkpoint_dir / "last.pt").is_file():
        resume_state = torch.load(checkpoint_dir / "last.pt", map_location="cpu", weights_only=False)
        for key in ("stage", "task", "model", "data", "loss", "optimization", "runtime"):
            if resume_state["config"].get(key) != config.get(key):
                raise ValueError(f"断点配置与当前{key}不一致，拒绝混合实验")
    audit_path = package_root / "results/reports/data_audit.json"
    audit_sha256 = hashlib.sha256(audit_path.read_bytes()).hexdigest() if audit_path.exists() else None
    if resume_state and resume_state.get("data_audit_sha256") != audit_sha256:
        raise ValueError("断点数据审计签名发生变化")
    print(json.dumps({"event": "preparing", "stage": config.get("stage"), "resuming": resume_state is not None}), flush=True)
    train_roots = [_resolve(package_root, value) for value in config["data"]["train_roots"]]
    if "frequencies_hz" in config["task"]:
        held_out_roots = {_resolve(package_root, value) for name in ("validation_roots", "test_roots") for value in config["data"][name]}
        if set(train_roots) & held_out_roots:
            raise ValueError("正式多场景训练与评估目录必须隔离")
    stats_path = checkpoint_dir / "normalization.json"
    stats_signature = hashlib.sha256(json.dumps({
        "task": config["task"], "split": config["data"].get("train_split", "train"),
        "manifests": [(str(p), hashlib.sha256((p / "manifest.json").read_bytes()).hexdigest()) for p in train_roots],
    }, sort_keys=True).encode()).hexdigest()
    if resume_state:
        normalization = resume_state["normalization"]
    elif "normalization" in config:
        normalization = dict(config["normalization"])
        if "per_frequency" in normalization:
            if any(float(item["std_db"]) <= 0 for item in normalization["per_frequency"].values()):
                raise ValueError("每个频段的normalization.std_db必须大于0")
        else:
            if float(normalization["std_db"]) <= 0:
                raise ValueError("normalization.std_db必须大于0")
            if not np.isclose(float(normalization["height_m"]), float(config["task"]["height_m"])):
                raise ValueError("normalization.height_m与任务高度不一致")
            if not np.isclose(float(normalization["frequency_hz"]), float(config["task"]["frequency_hz"])):
                raise ValueError("normalization.frequency_hz与任务频率不一致")
    elif config["optimization"].get("initial_checkpoint"):
        initial_path = _resolve(package_root, config["optimization"]["initial_checkpoint"])
        initial_state = torch.load(initial_path, map_location="cpu", weights_only=False)
        normalization = dict(initial_state["normalization"])
        del initial_state
    elif stats_path.is_file():
        cached = json.loads(stats_path.read_text())
        if cached["signature"] != stats_signature:
            raise ValueError("缓存归一化与训练集不一致")
        normalization = cached["normalization"]
    elif "frequencies_hz" in config["task"]:
        normalization = compute_multiband_statistics(
            roots=train_roots,
            split=str(config["data"].get("train_split", "train")),
            heights_m=config["task"]["pretrain_heights_m"],
            frequencies_hz=config["task"]["frequencies_hz"],
        )
    else:
        normalization = compute_rss_statistics(
            roots=train_roots,
            split="train",
            height_m=float(config["task"]["height_m"]),
            frequency_hz=float(config["task"]["frequency_hz"]),
        )
    atomic_write_text(stats_path, json.dumps({"signature": stats_signature, "normalization": normalization}, indent=2))
    print(json.dumps({"event": "normalization_ready", "normalization": normalization}), flush=True)
    train_dataset = _make_dataset(config, package_root, split="train", normalization=normalization)
    validation_dataset = _make_dataset(config, package_root, split="validation", normalization=normalization)
    print(json.dumps({"event": "cache_ready", "train_slices": len(train_dataset), "validation_slices": len(validation_dataset)}), flush=True)
    optimization = config["optimization"]
    worker_count = int(optimization.get("num_workers", 0))
    loader_kwargs: dict[str, Any] = {
        "batch_size": int(optimization["batch_size"]),
        "num_workers": worker_count,
        "pin_memory": device.type == "cuda",
    }
    if worker_count > 0:
        loader_kwargs.update({
            "persistent_workers": bool(optimization.get("persistent_workers", True)),
            "prefetch_factor": int(optimization.get("prefetch_factor", 4)),
        })
    train_loader = DataLoader(train_dataset, shuffle=True, drop_last=False, **loader_kwargs)
    validation_loader = DataLoader(validation_dataset, shuffle=False, drop_last=False, **loader_kwargs)
    if "per_frequency" in normalization:
        first_stats = next(iter(normalization["per_frequency"].values()))
        fallback_mean = float(first_stats["mean_dbm"])
        fallback_std = float(first_stats["std_db"])
    else:
        fallback_mean = float(normalization["mean_dbm"])
        fallback_std = float(normalization["std_db"])
    core_model = GeoTransUNet(
        **config["model"],
        rss_mean_dbm=fallback_mean,
        rss_std_db=fallback_std,
    ).to(device)
    initialization = None
    if optimization.get("initial_checkpoint") and resume_state is None:
        initial_path = _resolve(package_root, optimization["initial_checkpoint"])
        initialization = {
            "checkpoint": str(initial_path),
            **load_initial_weights(core_model, initial_path, device=device),
        }
        if initialization["unexpected_keys"]:
            raise ValueError(f"初始化checkpoint包含未知参数: {initialization['unexpected_keys']}")
        if any(not key.startswith("propagation_refiner.") for key in initialization["missing_keys"]):
            raise ValueError(f"初始化checkpoint缺少非refinement参数: {initialization['missing_keys']}")
    gpu_ids = usable_gpu_ids(
        [int(value) for value in config["runtime"].get("gpu_ids", [])],
        visible_device_count=torch.cuda.device_count(),
    )
    model: torch.nn.Module = core_model
    if device.type == "cuda" and len(gpu_ids) > 1:
        model = torch.nn.DataParallel(core_model, device_ids=gpu_ids)
    criterion = ShadowAwareLoss(
        **config.get("loss", {}),
        rss_std_db=fallback_std,
    )
    optimizer = AdamW(
        model.parameters(),
        lr=float(optimization["learning_rate"]),
        weight_decay=float(optimization["weight_decay"]),
    )
    epochs = int(optimization["epochs"])
    scheduler = CosineAnnealingLR(optimizer, T_max=max(epochs, 1))
    amp = bool(config["runtime"].get("amp", True)) and device.type == "cuda"
    amp_dtype_name = str(config["runtime"].get("amp_dtype", "bfloat16"))
    if amp_dtype_name not in {"bfloat16", "float16"}:
        raise ValueError("runtime.amp_dtype必须是bfloat16或float16")
    amp_dtype = torch.bfloat16 if amp_dtype_name == "bfloat16" else torch.float16
    scaler_enabled = amp and amp_dtype == torch.float16
    scaler = torch.amp.GradScaler(device.type, enabled=scaler_enabled)
    maximum_steps = optimization.get("max_train_steps")
    save_last_every = max(1, int(optimization.get("save_last_every", 5)))
    checkpoint_dir = _resolve(package_root, config["output"]["checkpoint_dir"])
    report_path = _resolve(package_root, config["output"]["report"])
    log_path = _resolve(package_root, config["output"].get("log", "logs/reconstruction_13m.jsonl"))
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    best_rmse = float("inf")
    history = []
    last_validation: dict[str, float] = {}
    optimizer_steps = 0
    started = time.time()
    start_epoch = 0
    if resume_state:
        core_model.load_state_dict(resume_state["model"])
        optimizer.load_state_dict(resume_state["optimizer"])
        scheduler.load_state_dict(resume_state["scheduler"])
        scaler.load_state_dict(resume_state["scaler"])
        start_epoch = int(resume_state["epoch"])
        optimizer_steps = int(resume_state["optimizer_steps"])
        best_rmse = float(resume_state["best_rmse_db"])
        history = list(resume_state["history"])
        last_validation = resume_state["validation"]
        rng = resume_state["rng"]
        random.setstate(rng["python"])
        np.random.set_state(rng["numpy"])
        torch.set_rng_state(rng["torch"])
        if device.type == "cuda":
            torch.cuda.set_rng_state_all(rng["cuda"])
        del resume_state
    temporary_log = log_path.with_suffix(".jsonl.tmp")
    temporary_log.write_text("".join(json.dumps(record) + "\n" for record in history))
    temporary_log.replace(log_path)
    for epoch in range(start_epoch, epochs):
        epoch_started = time.monotonic()
        train_dataset.set_epoch(epoch)
        model.train()
        train_loss_sum = 0.0
        train_steps = 0
        samples_seen = 0
        epoch_optimizer_steps = 0
        train_component_sums: dict[str, float] = {}
        for step, batch in enumerate(train_loader):
            if maximum_steps is not None and step >= int(maximum_steps):
                break
            tensor_batch = {key: value.to(device, non_blocking=True) for key, value in batch.items() if torch.is_tensor(value)}
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast(device_type=device.type, enabled=amp, dtype=amp_dtype):
                outputs = model(
                    tensor_batch["features"],
                    frequency_hz=tensor_batch.get("frequency_hz"),
                    height_m=tensor_batch.get("height_m"),
                    rss_mean_dbm=tensor_batch.get("rss_mean_dbm"),
                    rss_std_db=tensor_batch.get("rss_std_db"),
                )
                loss_terms = criterion(outputs, tensor_batch)
                loss = loss_terms["loss"]
            if not torch.isfinite(loss):
                raise FloatingPointError(f"非有限loss: epoch={epoch + 1}, step={step}")
            if scaler_enabled:
                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                clip_grad_norm_(model.parameters(), float(optimization.get("max_grad_norm", 1.0)), error_if_nonfinite=True)
                scale_before = scaler.get_scale()
                scaler.step(optimizer)
                scaler.update()
                if scaler.get_scale() >= scale_before:
                    epoch_optimizer_steps += 1
            else:
                loss.backward()
                clip_grad_norm_(model.parameters(), float(optimization.get("max_grad_norm", 1.0)), error_if_nonfinite=True)
                optimizer.step()
                epoch_optimizer_steps += 1
            train_loss_sum += float(loss.detach().cpu())
            for key, value in loss_terms.items():
                if key != "loss":
                    train_component_sums[key] = train_component_sums.get(key, 0.0) + float(value.cpu())
            train_steps += 1
            samples_seen += int(tensor_batch["features"].shape[0])
            if step % 100 == 0:
                print(json.dumps({"event": "train_step", "epoch": epoch + 1, "step": step, "loss": float(loss.detach()), "samples_seen": samples_seen}), flush=True)
        optimizer_steps += epoch_optimizer_steps
        if epoch_optimizer_steps > 0:
            scheduler.step()
        validation = _validate(model, validation_loader, device, amp=amp, amp_dtype=amp_dtype)
        last_validation = validation
        epoch_record = {
            "epoch": epoch + 1,
            "train_loss": train_loss_sum / max(train_steps, 1),
            "learning_rate": float(scheduler.get_last_lr()[0]),
            "optimizer_steps": epoch_optimizer_steps,
            "samples_seen": samples_seen,
            "epoch_seconds": time.monotonic() - epoch_started,
            **{
                f"train_{key}": value / max(train_steps, 1)
                for key, value in train_component_sums.items()
            },
            **{f"validation_{key}": value for key, value in validation.items()},
        }
        history.append(epoch_record)
        print(json.dumps(epoch_record), flush=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(epoch_record, ensure_ascii=False) + "\n")
        state = {
            "epoch": epoch + 1,
            "model": core_model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "config": config,
            "normalization": normalization,
            "scheduler": scheduler.state_dict(),
            "scaler": scaler.state_dict(),
            "optimizer_steps": optimizer_steps,
            "validation": validation,
        }
        if validation["rmse_db"] < best_rmse:
            best_rmse = validation["rmse_db"]
            atomic_torch_save({
                "epoch": epoch + 1,
                "model": core_model.state_dict(),
                "config": config,
                "normalization": normalization,
                "optimizer_steps": optimizer_steps,
                "validation": validation,
                "data_audit_sha256": audit_sha256,
            }, checkpoint_dir / "best.pt")
        state.update({"best_rmse_db": best_rmse, "history": history, "data_audit_sha256": audit_sha256,
                      "rng": {"python": random.getstate(), "numpy": np.random.get_state(), "torch": torch.get_rng_state(),
                              "cuda": torch.cuda.get_rng_state_all() if device.type == "cuda" else []}})
        if (epoch + 1) % save_last_every == 0 or epoch + 1 == epochs:
            atomic_torch_save(state, checkpoint_dir / "last.pt")
    # Test data is opened only after validation-based model selection.
    test_dataset = _make_dataset(config, package_root, split="test", normalization=normalization)
    test_loader = DataLoader(test_dataset, shuffle=False, drop_last=False, **loader_kwargs)
    report = {
        "stage": config.get("stage", "unspecified"),
        "task": config["task"],
        "train_samples": len(train_dataset),
        "validation_samples": len(validation_dataset),
        "test_samples": len(test_dataset),
        "parameter_count": sum(parameter.numel() for parameter in core_model.parameters()),
        "normalization": normalization,
        "initialization": initialization,
        "epochs": epochs,
        "elapsed_seconds": time.time() - started,
        "device": str(device),
        "gpu_count": len(gpu_ids) if device.type == "cuda" and gpu_ids else int(device.type == "cuda"),
        "amp_dtype": amp_dtype_name if amp else "disabled",
        "optimizer_steps": optimizer_steps,
        "validation": last_validation,
        "test": {},
        "best_rmse_db": best_rmse,
        "history": history,
    }
    best_state = torch.load(checkpoint_dir / "best.pt", map_location="cpu", weights_only=False)
    core_model.load_state_dict(best_state["model"])
    report["validation"] = dict(best_state["validation"])
    report["test"] = _validate(model, test_loader, device, amp=amp, amp_dtype=amp_dtype)
    temporary_report = report_path.with_suffix(".json.tmp")
    temporary_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_report.replace(report_path)
    return report
