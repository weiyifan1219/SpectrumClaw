"""Warm GenSpectra inference sidecar.

Runs under the GenSpectra/Agent_UAV python environment (which has torch + timm),
loads each resolution's model once and caches it in memory, then serves
inference over a tiny stdlib HTTP server. The main SpectrumClaw backend (a
different conda env without torch) talks to it via HTTP, so the model is loaded
once instead of per request.

The Agent_UAV env does not have FastAPI/uvicorn, so this deliberately uses only
the Python standard library plus torch/numpy (which the env already has).

Launch (GPU0 only, so the ingest job on GPU1 is never touched):

    CUDA_VISIBLE_DEVICES=0 \
    SPECTRUMCLAW_GENSPECTRA_ROOT=/workspace/YiFan/GenSpectra \
    /root/miniconda3/envs/Agent_UAV/bin/python -m backend.skills.spectrum_construction.genspectra_sidecar

Endpoints:
    GET  /health  -> {"status": "ok", "loaded": [resolutions...], "device": "..."}
    POST /infer   -> same JSON contract as genspectra_runner.py:
                     in : {"genspectra_root", "seed", "mask_ratio", "maps": [...]}
                     out: {"maps": [ {resolution, status, reconstruction, ...} ]}
"""

from __future__ import annotations

import gc
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np


ARCHITECTURES = {
    32: "mae_vit_base32_patch2",
    64: "mae_vit_base64_patch4",
    128: "mae_vit_base128_patch8",
    224: "mae_vit_base224_patch14",
}
PATCH_SPECS = {32: 2, 64: 4, 128: 8, 224: 14}
DEFAULT_NORM_MEAN = -62.11
DEFAULT_NORM_STD = 7.56

# Module-global caches — populated lazily on first inference for a resolution.
_TORCH: Any = None
_MODEL_MODULE: Any = None
_DEVICE: Any = None
_MODELS: dict[int, Any] = {}  # resolution -> loaded eval model


def _prepare_imports(genspectra_root: Path) -> None:
    visualization_root = genspectra_root / "results" / "visualization"
    sys.path.insert(0, str(visualization_root))
    sys.path.insert(0, str(genspectra_root))
    # GenSpectra's util.pos_embed uses the removed np.float alias.
    if not hasattr(np, "float"):
        np.float = float  # type: ignore[attr-defined]


def _ensure_runtime(genspectra_root: Path) -> None:
    global _TORCH, _MODEL_MODULE, _DEVICE
    if _TORCH is not None:
        return
    _prepare_imports(genspectra_root)
    import torch
    import model_mae_single

    _TORCH = torch
    _MODEL_MODULE = model_mae_single
    device_name = os.environ.get("SPECTRUMCLAW_GENSPECTRA_DEVICE")
    _DEVICE = torch.device(device_name or ("cuda" if torch.cuda.is_available() else "cpu"))


def _load_state_dict(checkpoint_path: Path) -> Any:
    torch = _TORCH
    try:
        checkpoint = torch.load(checkpoint_path, map_location=_DEVICE, weights_only=True)
    except TypeError:
        checkpoint = torch.load(checkpoint_path, map_location=_DEVICE)
    if isinstance(checkpoint, dict):
        return checkpoint.get("model") or checkpoint.get("state_dict") or checkpoint
    return checkpoint


def _get_model(resolution: int, checkpoint_path: Path) -> Any:
    """Build + load the model for a resolution once, then reuse the cached copy."""
    cached = _MODELS.get(resolution)
    if cached is not None:
        return cached

    factory = getattr(_MODEL_MODULE, ARCHITECTURES[resolution])
    model = factory(img_size=resolution) if resolution == 32 else factory()
    state_dict = _load_state_dict(checkpoint_path)
    model.load_state_dict(state_dict, strict=True)
    model.to(_DEVICE)
    model.eval()
    _MODELS[resolution] = model
    return model


def _matrix_for_json(matrix: np.ndarray) -> list[list[float | None]]:
    clean = np.where(np.isfinite(matrix), np.round(matrix, 4), np.nan)
    rows: list[list[float | None]] = []
    for row in clean.tolist():
        rows.append([None if np.isnan(value) else float(value) for value in row])
    return rows


def _run_one(
    *,
    item: dict[str, Any],
    resolution: int,
    seed: int,
    mask_ratio: float,
    norm_mean: float,
    norm_std: float,
) -> dict[str, Any]:
    torch = _TORCH
    patch_size = PATCH_SPECS[resolution]
    checkpoint_path = Path(item["checkpoint_path"])
    if not checkpoint_path.exists():
        return {
            "resolution": resolution,
            "status": "pending_checkpoint",
            "error": f"checkpoint not found: {checkpoint_path}",
        }

    torch.manual_seed(seed + resolution)
    if _DEVICE.type == "cuda":
        torch.cuda.manual_seed_all(seed + resolution)

    model = _get_model(resolution, checkpoint_path)

    original = np.array(item["original"], dtype=np.float32)
    normalized = ((original - norm_mean) / norm_std).astype(np.float32)
    x = torch.from_numpy(normalized[None, None, :, :]).to(device=_DEVICE, dtype=torch.float32)

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


def run_inference(payload: dict[str, Any]) -> dict[str, Any]:
    genspectra_root = Path(payload["genspectra_root"])
    seed = int(payload.get("seed", 0))
    mask_ratio = float(payload.get("mask_ratio", 0.75))
    norm_mean = float(os.environ.get("SPECTRUMCLAW_GENSPECTRA_MEAN", DEFAULT_NORM_MEAN))
    norm_std = float(os.environ.get("SPECTRUMCLAW_GENSPECTRA_STD", DEFAULT_NORM_STD))

    _ensure_runtime(genspectra_root)

    results = []
    for item in payload.get("maps", []):
        resolution = int(item["resolution"])
        try:
            result = _run_one(
                item=item,
                resolution=resolution,
                seed=seed,
                mask_ratio=mask_ratio,
                norm_mean=norm_mean,
                norm_std=norm_std,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to API response
            result = {"resolution": resolution, "status": "failed", "error": str(exc)}
        results.append(result)

    gc.collect()
    if _DEVICE is not None and _DEVICE.type == "cuda":
        _TORCH.cuda.empty_cache()
    return {"maps": results}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # silence per-request stderr noise
        pass

    def _send_json(self, code: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self._send_json(200, {
                "status": "ok",
                "loaded": sorted(_MODELS.keys()),
                "device": str(_DEVICE) if _DEVICE is not None else "uninitialized",
            })
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/infer":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            result = run_inference(payload)
            self._send_json(200, result)
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"error": str(exc)})


def main() -> int:
    host = os.environ.get("SPECTRUMCLAW_GENSPECTRA_HOST", "127.0.0.1")
    port = int(os.environ.get("SPECTRUMCLAW_GENSPECTRA_PORT", "8231"))

    # Warm all available checkpoints at startup so the first request is fast too.
    root = Path(os.environ.get("SPECTRUMCLAW_GENSPECTRA_ROOT", "/workspace/YiFan/GenSpectra"))
    try:
        _ensure_runtime(root)
        for resolution in ARCHITECTURES:
            ckpt = (
                root / "model" / "fixed_maskratio_0.75" / "pretrain"
                / f"pretrain_GenSpectraLM_{resolution}.pth"
            )
            if ckpt.exists():
                _get_model(resolution, ckpt)
        sys.stderr.write(
            f"[genspectra_sidecar] warm models={sorted(_MODELS.keys())} device={_DEVICE}\n"
        )
    except Exception as exc:  # noqa: BLE001 - degrade to lazy load on first request
        sys.stderr.write(f"[genspectra_sidecar] warmup skipped: {exc}\n")
    sys.stderr.flush()

    server = ThreadingHTTPServer((host, port), _Handler)
    sys.stderr.write(f"[genspectra_sidecar] listening on {host}:{port}\n")
    sys.stderr.flush()
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
