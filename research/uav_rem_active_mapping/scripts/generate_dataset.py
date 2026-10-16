#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
for path in (PACKAGE_ROOT / "src", REPOSITORY_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from uav_rem_active_mapping.config import load_dataset_config
from uav_rem_active_mapping.dataset_builder import build_dataset
from uav_rem_active_mapping.sionna_provider import SionnaRadioMapProvider
from uav_rem_active_mapping.validation import validate_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate formal Sionna RT UAV REM NPZ samples.")
    parser.add_argument("--config", type=Path, default=PACKAGE_ROOT / "configs" / "dataset" / "platform.yaml")
    parser.add_argument("--seed-start", type=int)
    parser.add_argument("--scene-count", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--asset-dir", type=Path)
    args = parser.parse_args()
    config = load_dataset_config(args.config)
    provider = SionnaRadioMapProvider(
        asset_dir=args.asset_dir or config.asset_dir,
        samples_per_tx=config.samples_per_tx,
        max_depth=config.max_depth,
        **config.rt_options,
    )
    if (args.seed_start is None) != (args.scene_count is None):
        raise ValueError("--seed-start 与 --scene-count 必须同时设置")
    scene_seeds = config.scene_seeds
    if args.seed_start is not None:
        if args.scene_count <= 0:
            raise ValueError("--scene-count 必须为正数")
        scene_seeds = tuple(range(args.seed_start, args.seed_start + args.scene_count))
    output_dir = args.output or config.output_dir
    manifest = build_dataset(
        output_dir=output_dir,
        provider=provider,
        scene_seeds=scene_seeds,
        split=config.split,
        spec=config.spec,
        transmitter_mode=config.transmitter_mode,
        source_count_cycle=config.source_count_cycle,
    )
    report = validate_dataset(output_dir)
    print({"manifest": manifest["sample_count"], "validation": report})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
