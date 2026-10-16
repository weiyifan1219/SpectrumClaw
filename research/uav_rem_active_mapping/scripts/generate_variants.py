#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
for path in (PACKAGE_ROOT / "src", REPOSITORY_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from uav_rem_active_mapping.config import load_dataset_config
from uav_rem_active_mapping.sionna_provider import SionnaRadioMapProvider
from uav_rem_active_mapping.variant_dataset import build_layout_dataset


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (PACKAGE_ROOT / path).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate paired Gazebo/Sionna urban-layout datasets.")
    parser.add_argument("--config", type=Path, default=PACKAGE_ROOT / "configs" / "dataset" / "pilot.yaml")
    parser.add_argument("--layouts", nargs="*", type=int, help="只生成指定layout；用于双GPU分片")
    args = parser.parse_args()
    raw = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    base = load_dataset_config(PACKAGE_ROOT / str(raw["base_config"]))
    provider = SionnaRadioMapProvider(
        asset_dir=base.asset_dir,
        samples_per_tx=base.samples_per_tx,
        max_depth=base.max_depth,
        **base.rt_options,
    )
    output_root = _resolve(str(raw["output_root"]))
    asset_root = _resolve(str(raw["asset_root"]))
    reports = []
    for item in raw["layouts"]:
        if args.layouts and int(item["layout_index"]) not in set(args.layouts):
            continue
        start = int(item["seed_start"])
        count = int(item["source_count"])
        reports.append(build_layout_dataset(
            output_root=output_root,
            asset_root=asset_root,
            provider=provider,
            layout_index=int(item["layout_index"]),
            split=str(item["split"]),
            source_seeds=range(start, start + count),
            spec=base.spec,
        ))
    if not reports:
        raise ValueError("配置中没有匹配 --layouts 的场景")
    print({"layout_count": len(reports), "sample_count": sum(item["sample_count"] for item in reports), "output_root": str(output_root)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
