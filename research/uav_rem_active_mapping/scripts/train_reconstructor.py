#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import torch
import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from uav_rem_active_mapping.training import resolve_stage_config, run_training


def main() -> int:
    parser = argparse.ArgumentParser(description="Pretrain or fine-tune the multiband REM reconstructor.")
    parser.add_argument("--config", type=Path, default=PACKAGE_ROOT / "configs" / "model" / "geotransunet.yaml")
    parser.add_argument("--stage", choices=("pretrain", "finetune"), default="pretrain")
    parser.add_argument("--sanity", action="store_true")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--initial-checkpoint", type=Path)
    parser.add_argument("--batch-size", type=int, choices=(32, 64))
    args = parser.parse_args()
    config = resolve_stage_config(
        yaml.safe_load(args.config.read_text(encoding="utf-8")),
        args.stage,
    )
    if args.sanity:
        config = copy.deepcopy(config)
        config["optimization"].update({"epochs": 1, "batch_size": 2, "max_train_steps": 2, "num_workers": 0})
        config["data"].update({"max_train_samples": 8, "max_validation_samples": 4, "max_test_samples": 4})
        config["output"].update({
            "checkpoint_dir": "checkpoints/reconstructor/sanity",
            "report": "results/reports/reconstruction_13m_sanity.json",
            "log": "logs/reconstruction_13m_sanity.jsonl",
        })
    if args.initial_checkpoint is not None:
        config["optimization"]["initial_checkpoint"] = str(args.initial_checkpoint)
    if args.batch_size is not None:
        config["optimization"]["batch_size"] = args.batch_size
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("3090训练环境未检测到CUDA")
    report = run_training(config, package_root=PACKAGE_ROOT, device=torch.device(args.device))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
