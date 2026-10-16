#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch
import yaml
from torch.utils.data import DataLoader


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from uav_rem_active_mapping.losses import ShadowAwareLoss
from uav_rem_active_mapping.models import GeoTransUNet
from uav_rem_active_mapping.training import _make_dataset, resolve_stage_config


def _repeat_batch(batch: dict[str, torch.Tensor], size: int) -> dict[str, torch.Tensor]:
    return {key: value[:1].repeat(size, *([1] * (value.ndim - 1))).cuda() for key, value in batch.items() if torch.is_tensor(value)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark physical training batch sizes on one RTX 3090.")
    parser.add_argument("--config", type=Path, default=PACKAGE_ROOT / "configs/model/geotransunet.yaml")
    parser.add_argument("--stage", choices=("pretrain", "finetune"), default="pretrain")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--sizes", nargs="+", type=int, default=(8, 16, 32, 48, 64))
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--output", type=Path, default=PACKAGE_ROOT / "results/reports/batch_benchmark.json")
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("batch benchmark必须在3090 CUDA环境运行")

    config = resolve_stage_config(yaml.safe_load(args.config.read_text(encoding="utf-8")), args.stage)
    checkpoint = args.checkpoint or PACKAGE_ROOT / config["output"]["checkpoint_dir"] / "best.pt"
    state = torch.load(checkpoint, map_location="cuda", weights_only=False)
    normalization = state["normalization"]
    if "per_frequency" in normalization:
        first_stats = next(iter(normalization["per_frequency"].values()))
        fallback_mean = float(first_stats["mean_dbm"])
        fallback_std = float(first_stats["std_db"])
    else:
        fallback_mean = float(normalization["mean_dbm"])
        fallback_std = float(normalization["std_db"])
    model = GeoTransUNet(
        **config["model"],
        rss_mean_dbm=fallback_mean,
        rss_std_db=fallback_std,
    ).cuda()
    incompatible = model.load_state_dict(state["model"], strict=False)
    if incompatible.unexpected_keys or any(
        not key.startswith("propagation_refiner.") for key in incompatible.missing_keys
    ):
        raise RuntimeError(f"checkpoint不兼容: {incompatible}")
    model.train()
    loss_fn = ShadowAwareLoss(**config["loss"], rss_std_db=fallback_std)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
    data_config = dict(config)
    data_config["data"] = dict(config["data"])
    data_config["data"].update({"cache_in_memory": False, "max_train_samples": 1})
    dataset = _make_dataset(data_config, PACKAGE_ROOT, split="train", normalization=normalization)
    sample = next(iter(DataLoader(dataset, batch_size=1, num_workers=0)))

    results = []
    for size in args.sizes:
        batch = _repeat_batch(sample, int(size))
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        try:
            durations = []
            for step in range(args.steps + 1):
                optimizer.zero_grad(set_to_none=True)
                torch.cuda.synchronize()
                started = time.perf_counter()
                with torch.amp.autocast("cuda", dtype=torch.bfloat16):
                    outputs = model(
                        batch["features"],
                        frequency_hz=batch.get("frequency_hz"),
                        height_m=batch.get("height_m"),
                        rss_mean_dbm=batch.get("rss_mean_dbm"),
                        rss_std_db=batch.get("rss_std_db"),
                    )
                    loss = loss_fn(outputs, batch)["loss"]
                loss.backward()
                optimizer.step()
                torch.cuda.synchronize()
                if step > 0:
                    durations.append(time.perf_counter() - started)
            mean_seconds = sum(durations) / len(durations)
            result = {
                "batch_size": int(size),
                "status": "ok",
                "step_seconds": mean_seconds,
                "samples_per_second": float(size) / mean_seconds,
                "peak_allocated_gb": torch.cuda.max_memory_allocated() / 2**30,
                "peak_reserved_gb": torch.cuda.max_memory_reserved() / 2**30,
            }
        except torch.cuda.OutOfMemoryError:
            optimizer.zero_grad(set_to_none=True)
            torch.cuda.empty_cache()
            result = {"batch_size": int(size), "status": "oom"}
        results.append(result)
        print(result, flush=True)
        del batch
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
