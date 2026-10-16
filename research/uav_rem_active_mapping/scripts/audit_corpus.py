#!/usr/bin/env python3
"""Fail closed before training: verify every file against the generation plan."""
from __future__ import annotations

import hashlib
import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from uav_rem_active_mapping.config import load_dataset_config
from uav_rem_active_mapping.data_io import load_sample
from uav_rem_active_mapping.scenes import SceneSpec, TransmitterSpec


def audit_root(root, spec, split, seeds, rt_options, global_ids):
    manifest_path = root / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    entries = manifest["samples"]
    if len(entries) != len(seeds) or manifest["sample_count"] != len(seeds):
        raise ValueError(f"样本数不符: {root}")
    if {int(item["seed"]) for item in entries} != set(seeds):
        raise ValueError(f"seed集合不符: {root}")
    paths = [(root / item["path"]).resolve() for item in entries]
    if len(set(paths)) != len(paths) or set(paths) != {p.resolve() for p in root.glob("*/*.npz")}:
        raise ValueError(f"NPZ路径重复、缺失或未入manifest: {root}")
    digest = hashlib.sha256(manifest_bytes)
    for item, path in zip(entries, paths):
        if not path.is_relative_to(root.resolve()):
            raise ValueError(f"非法样本路径: {path}")
        # Hash the exact bytes which are subsequently validated; the corpus is
        # immutable after this gate and the digest is retained with experiments.
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        sample = load_sample(path, spec)
        for key, expected in (("split", split), ("seed", item["seed"]), ("sample_id", item["sample_id"])):
            if sample[key].item() != expected:
                raise ValueError(f"{path}: {key}不符")
        identifier = str(sample["sample_id"].item())
        if identifier in global_ids:
            raise ValueError(f"重复sample_id: {identifier}")
        global_ids.add(identifier)
        for key in ("platform_world_id", "platform_world_sha256", "rf_geometry_id"):
            if sample[key].item() != manifest[key]:
                raise ValueError(f"{path}: {key}不符")
        rt = json.loads(sample["rt_config_json"].item())
        for key, expected in rt_options.items():
            if rt.get(key) != expected:
                raise ValueError(f"{path}: RT参数{key}不符")
        if "rt_plane_seeds" in sample or "rt_plane_attempts" in sample:
            attempts = sample["rt_plane_attempts"]
            if attempts.shape != spec.shape[:2] or not ((attempts >= 1) & (attempts <= 3)).all():
                raise ValueError(f"{path}: 无效RT重试次数")
            expected_seeds = (int(item["seed"]) * 10000 + np.arange(spec.frequency_count)[:,None]*100
                              + np.arange(spec.height_count)[None,:] + attempts - 1) % (2**32)
            np.testing.assert_array_equal(sample["rt_plane_seeds"], expected_seeds)
        scene = json.loads(sample["scene_config_json"].item())
        buildings = tuple((b["id"], tuple(b["center_m"]), tuple(b["size_m"])) for b in scene["buildings"])
        np.testing.assert_array_equal(sample["building_ids"], [b[0] for b in buildings])
        np.testing.assert_allclose(sample["building_centres_m"], [b[1] for b in buildings], atol=1e-5)
        np.testing.assert_allclose(sample["building_sizes_m"], [b[2] for b in buildings], atol=1e-5)
        tx = tuple(TransmitterSpec(tuple(t["position_m"]), tuple(t["powers_dbm"]), tuple(t["orientation_rad"])) for t in scene["transmitters"])
        for key, values in (("tx_positions_m", [t.position_m for t in tx]), ("tx_powers_dbm", [t.powers_dbm for t in tx]), ("tx_orientations_rad", [t.orientation_rad for t in tx])):
            np.testing.assert_allclose(sample[key], values, atol=1e-5)
        geometry = SceneSpec(scene["family_id"], scene["scene_id"], scene["asset_name"], scene["material_profile_id"], buildings, tx)
        height, valid, flyable = geometry.raster_masks(spec)
        np.testing.assert_allclose(sample["building_height_m"], height)
        np.testing.assert_array_equal(sample["valid_rx_mask"], valid)
        np.testing.assert_array_equal(sample["flyable_mask"], flyable)
    return {"root": str(root.relative_to(ROOT)), "split": split, "samples": len(entries), "sha256": digest.hexdigest()}


def audit_job(job):
    identifiers = set()
    return audit_root(*job, identifiers), identifiers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=("scenes", "platform", "all"), default="all")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        raise ValueError("workers必须位于1到16")
    plan = yaml.safe_load((ROOT / "configs/dataset/scenes.yaml").read_text())
    base = load_dataset_config(ROOT / plan["base_config"])
    expected_rt = {"samples_per_tx": base.samples_per_tx, "max_depth": base.max_depth, **base.rt_options}
    reports, identifiers, jobs = [], set(), []
    if args.scope in {"scenes", "all"}:
        for layout in plan["layouts"]:
            root = ROOT / plan["output_root"] / f"urban_layout_{layout['layout_index']:02d}"
            seeds = range(layout["seed_start"], layout["seed_start"] + layout["source_count"])
            jobs.append((root, base.spec, layout["split"], seeds, expected_rt))
    platform = load_dataset_config(ROOT / "configs/dataset/platform.yaml")
    if args.scope in {"platform", "all"}:
        for index in range(16):
            root = platform.output_dir / f"shard_{index:02d}"
            seeds = platform.scene_seeds[index*256:(index+1)*256]
            jobs.append((root, platform.spec, platform.split, seeds, expected_rt))
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for report, seen in pool.map(audit_job, jobs):
            if identifiers & seen:
                raise ValueError("跨数据集存在重复sample_id")
            identifiers.update(seen)
            reports.append(report)
            print(json.dumps(report), flush=True)
    payload = {"ok": True, "scope": args.scope, "sample_count": len(identifiers), "datasets": reports,
               "material_limitations": "ITU concrete XML uses the library default scattering coefficient 0.0; diffuse solver enabled does not imply nonzero diffuse power."}
    filename = "platform_audit.json" if args.scope == "platform" else "data_audit.json"
    path = ROOT / "results/reports" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


if __name__ == "__main__":
    main()
