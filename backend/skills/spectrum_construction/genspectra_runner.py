"""External GenSpectra pretrain inference runner.

This script is executed with the GenSpectra Python environment. It reads JSON
from stdin and writes JSON to stdout so SpectrumClaw does not import torch/timm
in its main backend process.
"""

from __future__ import annotations

import gc
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np


ARCHITECTURES = {
    32: "mae_vit_base32_patch2",
    64: "mae_vit_base64_patch4",
    128: "mae_vit_base128_patch8",
    224: "mae_vit_base224_patch14",
}
PATCH_SPECS = {
    32: 2,
    64: 4,
    128: 8,
    224: 14,
}
DEFAULT_NORM_MEAN = -62.11
DEFAULT_NORM_STD = 7.56


def main() -> int:
    payload = json.loads(sys.stdin.read())
    genspectra_root = Path(payload["genspectra_root"])
    seed = int(payload.get("seed", 0))
    mask_ratio = float(payload.get("mask_ratio", 0.75))
    norm_mean = float(os.environ.get("SPECTRUMCLAW_GENSPECTRA_MEAN", DEFAULT_NORM_MEAN))
    norm_std = float(os.environ.get("SPECTRUMCLAW_GENSPECTRA_STD", DEFAULT_NORM_STD))

    _prepare_imports(genspectra_root)

    import torch
    import model_mae_single

    device_name = os.environ.get("SPECTRUMCLAW_GENSPECTRA_DEVICE")
    device = torch.device(device_name or ("cuda" if torch.cuda.is_available() else "cpu"))
    results = []

    for item in payload.get("maps", []):
        resolution = int(item["resolution"])
        try:
            result = _run_one(
                torch=torch,
                model_module=model_mae_single,
                item=item,
                resolution=resolution,
                seed=seed,
                mask_ratio=mask_ratio,
                norm_mean=norm_mean,
                norm_std=norm_std,
                device=device,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to API response
            result = {
                "resolution": resolution,
                "status": "failed",
                "error": str(exc),
            }
        results.append(result)
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache()

    sys.stdout.write(json.dumps({"maps": results}, allow_nan=False))
    return 0


def _prepare_imports(genspectra_root: Path) -> None:
    visualization_root = genspectra_root / "results" / "visualization"
    sys.path.insert(0, str(visualization_root))
    sys.path.insert(0, str(genspectra_root))

    # GenSpectra's util.pos_embed uses np.float in the current server copy.
    if not hasattr(np, "float"):
        np.float = float  # type: ignore[attr-defined]


def _run_one(
    *,
    torch: Any,
    model_module: Any,
    item: dict[str, Any],
    resolution: int,
    seed: int,
    mask_ratio: float,
    norm_mean: float,
    norm_std: float,
    device: Any,
) -> dict[str, Any]:
    patch_size = PATCH_SPECS[resolution]
    checkpoint_path = Path(item["checkpoint_path"])
    if not checkpoint_path.exists():
        return {
            "resolution": resolution,
            "status": "pending_checkpoint",
            "error": f"checkpoint not found: {checkpoint_path}",
        }

    torch.manual_seed(seed + resolution)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed + resolution)

    factory = getattr(model_module, ARCHITECTURES[resolution])
    model = factory(img_size=resolution) if resolution == 32 else factory()
    state_dict = _load_state_dict(torch, checkpoint_path, device)
    model.load_state_dict(state_dict, strict=True)
    model.to(device)
    model.eval()

    original = np.array(item["original"], dtype=np.float32)
    normalized = ((original - norm_mean) / norm_std).astype(np.float32)
    x = torch.from_numpy(normalized[None, None, :, :]).to(device=device, dtype=torch.float32)

    with torch.no_grad():
        loss, pred, mask = model(x, mask_ratio=mask_ratio)
        reconstruction_norm = model.unpatchify(pred).detach().cpu().numpy()[0, 0]
        pixel_mask = mask.unsqueeze(-1).repeat(1, 1, patch_size**2)
        pixel_mask = model.unpatchify(pixel_mask).detach().cpu().numpy()[0, 0]

    reconstruction_norm = normalized * (1 - pixel_mask) + reconstruction_norm * pixel_mask
    reconstruction = reconstruction_norm * norm_std + norm_mean
    observed_mask = (1 - pixel_mask).astype(np.int32)
    masked = np.where(observed_mask == 1, original, np.nan)
    rmse = float(np.sqrt(np.mean((original - reconstruction) ** 2)))

    return {
        "resolution": resolution,
        "status": "ready",
        "loss": float(loss.detach().cpu()),
        "masked": _matrix_for_json(masked),
        "observed_mask": observed_mask.astype(int).tolist(),
        "reconstruction": _matrix_for_json(reconstruction),
        "rmse": rmse,
    }


def _load_state_dict(torch: Any, checkpoint_path: Path, device: Any) -> Any:
    try:
        checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=True)
    except TypeError:
        checkpoint = torch.load(checkpoint_path, map_location=device)
    if isinstance(checkpoint, dict):
        return checkpoint.get("model") or checkpoint.get("state_dict") or checkpoint
    return checkpoint


def _matrix_for_json(matrix: np.ndarray) -> list[list[float | None]]:
    clean = np.where(np.isfinite(matrix), np.round(matrix, 4), np.nan)
    rows: list[list[float | None]] = []
    for row in clean.tolist():
        rows.append([None if np.isnan(value) else float(value) for value in row])
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
