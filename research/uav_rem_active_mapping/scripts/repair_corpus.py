#!/usr/bin/env python3
"""Recover indexes from verified NPZ files; quarantine corrupt files for RT replay."""
from __future__ import annotations

import json
import sys
import zipfile
import zlib
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from uav_rem_active_mapping.config import load_dataset_config
from uav_rem_active_mapping.data_io import load_sample, atomic_write_text
from uav_rem_active_mapping.scene_variants import urban_layout, export_layout_assets
from uav_rem_active_mapping.platform_binding import binding_from_world


def recover_layout(job):
    item, output_root, asset_root, spec, quarantine = job
    scene = urban_layout(layout_index=item["layout_index"], split=item["split"])
    root = ROOT / output_root / scene.scene_id
    assets = export_layout_assets(scene, ROOT / asset_root, split=item["split"], rebuild=True)
    binding = binding_from_world(world_id=scene.scene_id, world_path=assets.gazebo_world_path,
                                 rf_geometry_id=f"canonical_scene.{scene.scene_id}.v1")
    entries, corrupt, missing = [], [], []
    for seed in range(item["seed_start"], item["seed_start"] + item["source_count"]):
        sample_id = f"{scene.family_id}-{seed:08d}"
        path = root / item["split"] / f"{sample_id}.npz"
        if not path.exists():
            missing.append(seed)
            continue
        try:
            sample = load_sample(path, spec)
            for key, expected in (("seed", seed), ("sample_id", sample_id), ("split", item["split"]),
                                  ("platform_world_sha256", binding.world_sha256)):
                if sample[key].item() != expected:
                    raise ValueError(f"{key} does not match generation plan")
            # Force JSON decoding now so the recovered index cannot bless null-filled metadata.
            for key in ("scene_config_json", "generation_config_json", "rt_config_json", "units_json"):
                json.loads(sample[key].item())
        except (ValueError, KeyError, EOFError, zipfile.BadZipFile, zlib.error, UnicodeError) as error:
            destination = quarantine / path.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            path.rename(destination)
            corrupt.append({"seed": seed, "path": str(path.relative_to(ROOT)), "reason": str(error)})
            missing.append(seed)
            continue
        entries.append({"path": str(path.relative_to(root)), "sample_id": sample_id, "seed": seed,
                        "split": item["split"], "transmitter_count": int(sample["tx_positions_m"].shape[0])})
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        try:
            json.loads(manifest_path.read_text())
        except (ValueError, UnicodeError):
            backup = quarantine / manifest_path.relative_to(ROOT)
            backup.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.rename(backup)
    manifest = {
        "schema_version": spec.schema_version, "provider": "sionna_rt", "axis_order": spec.axis_order,
        "shape": list(spec.shape), "frequencies_hz": list(spec.frequencies_hz), "heights_m": list(spec.heights_m),
        "bounds_enu_m": list(spec.bounds_enu_m), "scene_id": scene.scene_id, "scene_family_id": scene.family_id,
        "split": item["split"], "platform_world_id": binding.world_id, "platform_world_sha256": binding.world_sha256,
        "rf_geometry_id": binding.rf_geometry_id, "gazebo_world": str(assets.gazebo_world_path),
        "sionna_xml": str(assets.sionna_xml_path), "source_count_cycle": [1,2,3],
        "sample_count": len(entries), "samples": entries,
    }
    atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
    return {"layout": scene.scene_id, "split": item["split"], "valid": len(entries),
            "missing_seeds": missing, "quarantined": corrupt}


def main():
    plan = yaml.safe_load((ROOT / "configs/dataset/scenes.yaml").read_text())
    spec = load_dataset_config(ROOT / plan["base_config"]).spec
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    quarantine = ROOT / "artifacts/quarantine" / stamp
    quarantine.mkdir(parents=True, exist_ok=False)
    jobs = [(item, plan["output_root"], plan["asset_root"], spec, quarantine) for item in plan["layouts"]]
    reports = []
    with ProcessPoolExecutor(max_workers=8) as pool:
        for result in pool.map(recover_layout, jobs):
            reports.append(result)
            print(json.dumps({k: v if not isinstance(v, list) else len(v) for k, v in result.items()}), flush=True)
    report = {"valid": sum(r["valid"] for r in reports), "missing": sum(len(r["missing_seeds"]) for r in reports),
              "quarantined": sum(len(r["quarantined"]) for r in reports), "quarantine": str(quarantine), "layouts": reports}
    atomic_write_text(ROOT / "results/reports/data_recovery.json", json.dumps(report, indent=2))
    print(json.dumps({k:v for k,v in report.items() if k != "layouts"}), flush=True)


if __name__ == "__main__":
    main()
