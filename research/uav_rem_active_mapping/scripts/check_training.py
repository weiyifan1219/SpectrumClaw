#!/usr/bin/env python3
"""Two real optimizer steps with the full model before an unattended run."""
import gc
import json
import sys
from pathlib import Path

import torch
import yaml
from torch.utils.data import default_collate

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from uav_rem_active_mapping.training import resolve_stage_config
from uav_rem_active_mapping.training_data import MultiBandHeightDataset, compute_multiband_statistics
from uav_rem_active_mapping.models import GeoTransUNet
from uav_rem_active_mapping.losses import ShadowAwareLoss


def check(batch_size, config, dataset):
    model = GeoTransUNet(**config["model"]).cuda()
    if torch.cuda.device_count() != 2:
        raise RuntimeError("正式预检需要两张可用3090")
    parallel = torch.nn.DataParallel(model, device_ids=[0, 1])
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["optimization"]["learning_rate"])
    criterion = ShadowAwareLoss(**config["loss"])
    batch = default_collate([dataset[i % len(dataset)] for i in range(batch_size)])
    batch = {k: v.cuda() for k, v in batch.items() if torch.is_tensor(v)}
    losses = []
    for i in range(2):
        optimizer.zero_grad(set_to_none=True)
        with torch.amp.autocast("cuda", dtype=torch.bfloat16):
            outputs = parallel(batch["features"], **{k: batch[k] for k in ("frequency_hz", "height_m", "rss_mean_dbm", "rss_std_db")})
            loss = criterion(outputs, batch)["loss"]
        if not torch.isfinite(loss):
            raise FloatingPointError("预检loss不是有限值")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()
        losses.append(float(loss.detach()))
    return {"ok": True, "batch_size": batch_size, "losses": losses,
            "parameter_count": sum(p.numel() for p in model.parameters()),
            "peak_allocated_gib": [torch.cuda.max_memory_allocated(i) / 2**30 for i in range(2)],
            "note": "readiness only; statistics are from one train layout, not used for formal training"}


def main():
    config = resolve_stage_config(yaml.safe_load((ROOT / "configs/model/geotransunet.yaml").read_text()), "pretrain")
    roots = [ROOT / config["data"]["train_roots"][0]]
    # No validation/test files are touched during the readiness check.
    stats = compute_multiband_statistics(roots=roots, split="pretrain", heights_m=config["task"]["pretrain_heights_m"], frequencies_hz=config["task"]["frequencies_hz"])
    dataset = MultiBandHeightDataset(roots=roots, split="pretrain", heights_m=config["task"]["pretrain_heights_m"],
                                    frequencies_hz=config["task"]["frequencies_hz"], normalization=stats,
                                    sample_rate_range=[0.01, 0.25], mask_modes=["random"], max_samples=1, cache_in_memory=True)
    result = None
    for size in (64, 32):
        try:
            for index in range(2):
                torch.cuda.reset_peak_memory_stats(index)
            result = check(size, config, dataset)
            break
        except torch.cuda.OutOfMemoryError:
            print(f"readiness OOM at total batch {size}", flush=True)
        gc.collect()
        torch.cuda.empty_cache()
    if result is None:
        raise RuntimeError("batch32和64均未通过显存预检")
    path = ROOT / "results/reports/training_check.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=2))
    tmp.replace(path)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
