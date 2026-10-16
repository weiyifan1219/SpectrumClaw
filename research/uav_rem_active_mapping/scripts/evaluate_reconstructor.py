#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import torch
import yaml
from torch.utils.data import DataLoader


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from uav_rem_active_mapping.models import GeoTransUNet
from uav_rem_active_mapping.training import _make_dataset, _validate, resolve_stage_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the 13 m reconstructor at fixed sampling budgets.")
    parser.add_argument("--config", type=Path, default=PACKAGE_ROOT / "configs/model/geotransunet.yaml")
    parser.add_argument("--stage", choices=("pretrain", "finetune"), default="pretrain")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    parser.add_argument("--rates", nargs="+", type=float, default=(0.0, 0.01, 0.03, 0.05))
    parser.add_argument("--mode", choices=("trajectory", "random", "clustered"), default="trajectory")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--height-m", type=float, default=13.0)
    parser.add_argument("--platform", action="store_true", help="评估完全留出的urban_block平台分片")
    parser.add_argument("--output", type=Path, default=PACKAGE_ROOT / "results/reports/reconstruction_13m_by_budget.json")
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("固定预算评测必须在3090 CUDA环境运行")
    config = resolve_stage_config(yaml.safe_load(args.config.read_text(encoding="utf-8")), args.stage)
    checkpoint = args.checkpoint or PACKAGE_ROOT / config["output"]["checkpoint_dir"] / "best.pt"
    state = torch.load(checkpoint, map_location="cuda", weights_only=False)
    normalization = state["normalization"]
    model_config = state["config"]["model"]
    if "per_frequency" in normalization:
        first_stats = next(iter(normalization["per_frequency"].values()))
        fallback_mean = float(first_stats["mean_dbm"])
        fallback_std = float(first_stats["std_db"])
    else:
        fallback_mean = float(normalization["mean_dbm"])
        fallback_std = float(normalization["std_db"])
    model = GeoTransUNet(
        **model_config,
        rss_mean_dbm=fallback_mean,
        rss_std_db=fallback_std,
    ).cuda()
    model.load_state_dict(state["model"])
    config["task"]["pretrain_heights_m"] = [args.height_m]
    config["task"]["finetune_height_m"] = args.height_m
    if args.platform:
        config["data"][f"{args.split}_roots"] = [f"data/raw_gt/platform_multiband/shard_{i:02d}" for i in range(16)]
        config["data"][f"{args.split}_split"] = "platform_test"
    results = {}
    dataset = None
    for rate in args.rates:
        if not 0.0 <= rate <= 0.05:
            raise ValueError("评测采样率必须位于[0,0.05]")
        run_config = copy.deepcopy(config)
        run_config["data"].pop("sample_rate_range", None)
        run_config["data"]["sample_rates"] = [float(rate)]
        run_config["data"]["mask_modes"] = [args.mode]
        if args.max_samples is not None:
            run_config["data"][f"max_{args.split}_samples"] = int(args.max_samples)
        if dataset is None:
            dataset = _make_dataset(run_config, PACKAGE_ROOT, split=args.split, normalization=normalization)
        else:
            dataset.sample_rates = (float(rate),)
        loader = DataLoader(
            dataset,
            batch_size=args.batch_size,
            shuffle=False,
            num_workers=0,
            pin_memory=True,
        )
        metrics = _validate(model, loader, torch.device("cuda"), amp=True, amp_dtype=torch.bfloat16, grouped=True)
        results[f"{100.0 * rate:.1f}%"] = metrics
        print(f"rate={rate:.4f} rmse={metrics['rmse_db']:.4f} dB", flush=True)
    payload = {
        "checkpoint": str(checkpoint),
        "stage": args.stage,
        "split": args.split,
        "mode": args.mode,
        "height_m": args.height_m,
        "domain": "platform" if args.platform else "held_out_layouts",
        "frequencies_hz": config["task"].get("frequencies_hz", [config["task"].get("frequency_hz")]),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
