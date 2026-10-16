from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .contracts import DatasetSpec
from .data_io import load_sample


def validate_dataset(root: str | Path) -> dict:
    dataset_root = Path(root)
    manifest_path = dataset_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    spec = DatasetSpec(
        rows=int(manifest["shape"][2]),
        columns=int(manifest["shape"][3]),
        frequencies_hz=tuple(float(value) for value in manifest["frequencies_hz"]),
        heights_m=tuple(float(value) for value in manifest["heights_m"]),
        bounds_enu_m=tuple(float(value) for value in manifest["bounds_enu_m"]),
    )
    if manifest.get("provider") != "sionna_rt":
        raise ValueError("manifest provider 必须是 sionna_rt")
    entries = manifest["samples"]
    if not entries or len(entries) != int(manifest["sample_count"]):
        raise ValueError("manifest sample_count 与实际条目数不一致")
    for field in ("path", "sample_id"):
        if len({item[field] for item in entries}) != len(entries):
            raise ValueError(f"manifest 包含重复 {field}")
    for field in ("platform_world_id", "platform_world_sha256", "rf_geometry_id"):
        if field not in manifest:
            raise ValueError(f"manifest 缺少平台绑定字段: {field}")
    rss_min, rss_max = float("inf"), -float("inf")
    providers, families = set(), set()
    for item in entries:
        path = (dataset_root / item["path"]).resolve()
        if not path.is_relative_to(dataset_root.resolve()):
            raise ValueError("manifest路径超出数据目录")
        sample = load_sample(path, spec)
        for field in ("platform_world_id", "platform_world_sha256", "rf_geometry_id"):
            if str(sample[field].item()) != str(manifest[field]):
                raise ValueError(f"样本 {field} 与 manifest 平台绑定不一致")
        for field in ("sample_id", "seed", "split"):
            if field in item and sample[field].item() != item[field]:
                raise ValueError(f"样本 {field} 与 manifest 条目不一致")
        rss_min = min(rss_min, float(sample["rss_dbm"].min()))
        rss_max = max(rss_max, float(sample["rss_dbm"].max()))
        providers.add(str(sample["provider"].item()))
        families.add(str(sample["scene_family_id"].item()))
    return {
        "ok": True,
        "sample_count": len(entries),
        "shape": list(spec.shape),
        "providers": sorted(providers),
        "rss_min_dbm": rss_min,
        "rss_max_dbm": rss_max,
        "scene_families": sorted(families),
        "platform_world_id": manifest["platform_world_id"],
        "platform_world_sha256": manifest["platform_world_sha256"],
        "rf_geometry_id": manifest["rf_geometry_id"],
    }
