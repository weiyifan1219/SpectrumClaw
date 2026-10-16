#!/usr/bin/env python3
"""Recover valid NPZs and regenerate missing samples on a healthy RAM filesystem."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import yaml


def _bootstrap(root: Path) -> None:
    repository = Path("/workspace/YiFan/SpectrumClaw")
    for path in (root / "src", repository):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _validate(path: Path, spec) -> dict:
    from uav_rem_active_mapping.data_io import load_sample
    sample = load_sample(path, spec)
    for key in ("scene_config_json", "generation_config_json", "rt_config_json", "units_json"):
        json.loads(sample[key].item())
    return sample


def copy_one(job):
    source, destination, root = map(Path, job)
    _bootstrap(root)
    from uav_rem_active_mapping.config import load_dataset_config
    spec = load_dataset_config(root / "configs/dataset/multiband.yaml").spec
    try:
        if destination.exists():
            _validate(destination, spec)
            return "existing", str(destination)
        _validate(source, spec)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(".copy_" + destination.name)
        shutil.copyfile(source, temporary)
        _validate(temporary, spec)
        temporary.replace(destination)
        return "copied", str(destination)
    except Exception as error:
        return "invalid", f"{source}: {type(error).__name__}: {str(error)[:160]}"


def stage_valid(source_root: Path, target_root: Path, workers: int) -> dict:
    source = source_root / "data/raw_gt/multiband"
    target = target_root / "data/raw_gt/multiband"
    jobs = [(path, target / path.relative_to(source), target_root) for path in sorted(source.glob("*/*/*.npz"))]
    counts = {"copied": 0, "existing": 0, "invalid": 0}
    errors = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for index, (status, detail) in enumerate(pool.map(copy_one, jobs, chunksize=8), 1):
            counts[status] += 1
            if status == "invalid" and len(errors) < 100:
                errors.append(detail)
            if index % 512 == 0:
                print(json.dumps({"event": "staging", "scanned": index, **counts}), flush=True)
    return {**counts, "errors": errors}


def worker(target_root: Path, layout_indices: list[int]) -> None:
    _bootstrap(target_root)
    from uav_rem_active_mapping.config import load_dataset_config
    from uav_rem_active_mapping.sionna_provider import SionnaRadioMapProvider
    from uav_rem_active_mapping.variant_dataset import build_layout_dataset
    plan = yaml.safe_load((target_root / "configs/dataset/scenes.yaml").read_text())
    base = load_dataset_config(target_root / plan["base_config"])
    provider = SionnaRadioMapProvider(
        asset_dir=target_root / "data/sionna_assets/multiband",
        samples_per_tx=base.samples_per_tx,
        max_depth=base.max_depth,
        **base.rt_options,
    )
    selected = set(layout_indices)
    for item in plan["layouts"]:
        if item["layout_index"] not in selected:
            continue
        build_layout_dataset(
            output_root=target_root / "data/raw_gt/multiband",
            asset_root=target_root / "data/scene_assets/multiband",
            provider=provider,
            layout_index=item["layout_index"],
            split=item["split"],
            source_seeds=range(item["seed_start"], item["seed_start"] + item["source_count"]),
            spec=base.spec,
        )
        print(json.dumps({"event": "layout_complete", "layout": item["layout_index"]}), flush=True)


def free_gib(path: Path) -> float:
    return shutil.disk_usage(path).free / 2**30


def run_workers(target_root: Path, count: int, min_free_gib: float) -> None:
    logs = target_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    groups = [[layout for layout in range(1, 35) if (layout - 1) % count == index] for index in range(count)]
    attempts = 0
    while attempts < 3:
        attempts += 1
        processes = []
        for index, layouts in enumerate(groups):
            gpu = 0 if index < count // 2 else 1
            handle = (logs / f"rebuild_{index:02d}.log").open("a", encoding="utf-8")
            env = os.environ.copy()
            env.update(CUDA_VISIBLE_DEVICES=str(gpu), PYTHONPATH=f"{target_root / 'src'}:/workspace/YiFan/SpectrumClaw")
            process = subprocess.Popen(
                [sys.executable, str(target_root / "scripts/rebuild_shm.py"), "--worker", *map(str, layouts), "--target-root", str(target_root)],
                stdout=handle, stderr=subprocess.STDOUT, env=env,
            )
            processes.append((process, handle))
        while any(process.poll() is None for process, _ in processes):
            if free_gib(target_root) < min_free_gib:
                for process, _ in processes:
                    process.terminate()
                raise RuntimeError(f"RAM盘剩余空间低于{min_free_gib} GiB，已停止")
            print(json.dumps({"event": "workers_running", "attempt": attempts, "free_gib": round(free_gib(target_root), 2)}), flush=True)
            time.sleep(60)
        failures = []
        for process, handle in processes:
            handle.close()
            if process.returncode:
                failures.append(process.returncode)
        if not failures:
            return
        print(json.dumps({"event": "worker_retry", "attempt": attempts, "failures": len(failures)}), flush=True)
    raise RuntimeError("RAM盘数据生成连续三次未完成")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path("/workspace/YiFan/SpectrumClaw/research/uav_rem_active_mapping"))
    parser.add_argument("--target-root", type=Path, default=Path("/dev/shm/uav_rem_active_mapping"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--min-free-gib", type=float, default=6.0)
    parser.add_argument("--worker", nargs="*", type=int)
    args = parser.parse_args()
    if args.worker is not None:
        worker(args.target_root, args.worker)
        return 0
    if not 1 <= args.workers <= 8 or args.workers % 2:
        raise ValueError("workers必须是2、4、6或8")
    report = stage_valid(args.source_root, args.target_root, args.workers)
    print(json.dumps({"event": "staging_complete", **{k: v for k, v in report.items() if k != 'errors'}}), flush=True)
    if free_gib(args.target_root) < args.min_free_gib:
        raise RuntimeError("复制有效样本后RAM盘空间不足")
    run_workers(args.target_root, args.workers, args.min_free_gib)
    marker = args.target_root / "results/reports/shm_generation.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    files = list((args.target_root / "data/raw_gt/multiband").glob("*/*/*.npz"))
    payload = {"ok": len(files) == 17408, "npz_count": len(files), "free_gib": free_gib(args.target_root), "staging": report}
    marker.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload), flush=True)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
