from __future__ import annotations

import math

import torch


def reconstruction_metric_sums(
    outputs: dict[str, torch.Tensor],
    batch: dict[str, torch.Tensor],
) -> dict[str, torch.Tensor]:
    target = batch["target_dbm"]
    mask = batch["valid_mask"].to(target.dtype) * (1.0 - batch["observed_mask"].to(target.dtype))
    error = outputs["mean_dbm"] - target
    scale = outputs["scale_db"].clamp(0.25, 30.0)
    shadow_mask = mask * (batch["shadow_target"].to(target.dtype) >= 0.5).to(target.dtype)
    interval = math.log(10.0) * scale
    return {
        "count": mask.sum(),
        "absolute_error": (torch.abs(error) * mask).sum(),
        "squared_error": (error.square() * mask).sum(),
        "nll": ((torch.abs(error) / scale + torch.log(2.0 * scale)) * mask).sum(),
        "covered_90": ((torch.abs(error) <= interval).to(target.dtype) * mask).sum(),
        "shadow_count": shadow_mask.sum(),
        "shadow_squared_error": (error.square() * shadow_mask).sum(),
    }


def finalize_metric_sums(sums: dict[str, float]) -> dict[str, float]:
    count = max(float(sums["count"]), 1.0)
    shadow_count = max(float(sums["shadow_count"]), 1.0)
    return {
        "mae_db": float(sums["absolute_error"]) / count,
        "rmse_db": math.sqrt(float(sums["squared_error"]) / count),
        "nll": float(sums["nll"]) / count,
        "picp90": float(sums["covered_90"]) / count,
        "shadow_rmse_db": math.sqrt(float(sums["shadow_squared_error"]) / shadow_count),
        "evaluated_cells": int(float(sums["count"])),
        "shadow_cells": int(float(sums["shadow_count"])),
    }
