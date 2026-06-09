"""Gudmundson spectrum construction preview generation.

This is the executable subset of
`/workspace/YiFan/GenSpectra/Gudmundsom/Generators/gudmundson_generator.ipynb`.
When the GenSpectra runtime and checkpoints are available, reconstruction is
delegated to a small external runner so this process does not need torch/timm.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_RESOLUTIONS = [32, 64, 128, 224]
DEFAULT_MASK_RATIO = 0.75
DEFAULT_TX_POWER = [14.0, 20.0]
DEFAULT_FREQUENCY_HZ = 1.4e9
DEFAULT_MODEL_VARIANT = "pretrain"
DEFAULT_GENSPECTRA_ROOT = Path("/workspace/YiFan/GenSpectra")
DEFAULT_GENSPECTRA_PYTHON = Path("/root/miniconda3/envs/Agent_UAV/bin/python")
PATCH_SPECS = {
    32: 2,
    64: 4,
    128: 8,
    224: 14,
}


def dbm_to_natural(dbm: np.ndarray | list[float] | float) -> np.ndarray:
    return 10 ** (np.array(dbm, dtype=float) / 10)


def natural_to_db(natural: np.ndarray) -> np.ndarray:
    return 10 * np.log10(natural + 1e-10)


class GudmundsonMapGenerator:
    """Small, deterministic Gudmundson path-loss map generator."""

    def __init__(
        self,
        *,
        rng: np.random.Generator,
        resolution: int,
        v_central_frequencies: list[float] | None = None,
        tx_power: list[float] | None = None,
        n_tx: int = 2,
        tx_power_interval: list[float] | None = None,
        path_loss_exp: float = 3.0,
        x_length: float = 100.0,
        y_length: float = 100.0,
    ) -> None:
        self.rng = rng
        self.v_central_frequencies = v_central_frequencies or [DEFAULT_FREQUENCY_HZ]
        self.tx_power = tx_power
        self.n_tx = n_tx
        self.tx_power_interval = tx_power_interval or [14.0, 20.0]
        self.path_loss_exp = path_loss_exp
        self.x_length = x_length
        self.y_length = y_length
        self.nx = resolution
        self.ny = resolution
        self.eps = min(self.x_length / self.nx, self.y_length / self.ny)
        self.m_basis_functions = np.ones((1,))
        self.x_grid, self.y_grid = np.meshgrid(
            np.linspace(0, x_length, self.nx),
            np.linspace(0, y_length, self.ny),
        )
        self.source_positions: np.ndarray | None = None

    def generate_power_map(self) -> np.ndarray:
        self.source_positions = np.column_stack(
            [
                self.rng.uniform(5, self.x_length - 5, self.n_tx),
                self.rng.uniform(5, self.y_length - 5, self.n_tx),
            ]
        )

        if self.tx_power is not None:
            tx_power_mw = dbm_to_natural(np.array(self.tx_power).reshape(1, -1))
        else:
            tx_power_mw = dbm_to_natural(
                self.rng.uniform(
                    self.tx_power_interval[0],
                    self.tx_power_interval[1],
                    (len(self.v_central_frequencies), self.n_tx),
                )
            )

        dists = np.sqrt(
            (self.x_grid[None, :, :] - self.source_positions[:, 0][:, None, None]) ** 2
            + (self.y_grid[None, :, :] - self.source_positions[:, 1][:, None, None]) ** 2
        ) + self.eps

        total_power = np.zeros((self.ny, self.nx), dtype=float)
        c_light = 3e8
        n_bases = self.m_basis_functions.shape[0]

        for freq in self.v_central_frequencies:
            wavelength = c_light / freq
            k = (wavelength / (4 * np.pi)) ** 2
            if self.tx_power is not None:
                tx_power_to_use = np.repeat(tx_power_mw, n_bases, axis=0).reshape(
                    n_bases, self.n_tx
                ).T
            else:
                tx_power_to_use = self.rng.uniform(
                    tx_power_mw.min(), tx_power_mw.max(), size=(self.n_tx, n_bases)
                )
            tx_power_to_use = tx_power_to_use[:, :, None, None]
            power_from_bases = (tx_power_to_use * k) / (
                dists[:, None, :, :] ** self.path_loss_exp
            )
            total_power += np.sum(np.sum(power_from_bases, axis=1), axis=0)

        return total_power


def build_multi_resolution_preview(
    *,
    seed: int = 0,
    resolutions: list[int] | None = None,
    mask_ratio: float = DEFAULT_MASK_RATIO,
    model_variant: str = DEFAULT_MODEL_VARIANT,
    enable_inference: bool = False,
    tx_power: list[float] | None = None,
    n_tx: int = 2,
    frequency_hz: float = DEFAULT_FREQUENCY_HZ,
    output_root: str | Path | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    if not 0 < mask_ratio < 1:
        raise ValueError("mask_ratio must be between 0 and 1")
    if model_variant != DEFAULT_MODEL_VARIANT:
        raise ValueError(f"unsupported model_variant: {model_variant}")
    selected_resolutions = resolutions or DEFAULT_RESOLUTIONS
    for resolution in selected_resolutions:
        if resolution not in DEFAULT_RESOLUTIONS:
            raise ValueError(f"unsupported resolution: {resolution}")

    rng = np.random.default_rng(seed)
    maps = []
    raw_maps: list[dict[str, Any]] = []
    default_inference_status = "pending_checkpoint" if enable_inference else "inference_disabled"

    for resolution in selected_resolutions:
        generator = GudmundsonMapGenerator(
            rng=rng,
            resolution=resolution,
            v_central_frequencies=[frequency_hz],
            tx_power=tx_power or DEFAULT_TX_POWER,
            n_tx=n_tx,
        )
        original = natural_to_db(generator.generate_power_map())
        observed_mask = _fixed_patch_mask(rng, resolution, mask_ratio=mask_ratio)
        masked = np.where(observed_mask == 1, original, np.nan)
        patch_size = PATCH_SPECS[resolution]
        checkpoint_path = _checkpoint_path(_genspectra_root(), resolution)

        maps.append(
            {
                "resolution": resolution,
                "patch_size": patch_size,
                "patch_grid": [resolution // patch_size, resolution // patch_size],
                "mask_unit": "vit_patch",
                "original": _matrix_for_json(original),
                "masked": _matrix_for_json(masked),
                "observed_mask": observed_mask.astype(int).tolist(),
                "reconstruction": None,
                "rmse": None,
                "inference_status": default_inference_status,
                "inference_error": None,
                "checkpoint_path": str(checkpoint_path),
                "source_positions": _round_matrix(generator.source_positions),
                "metrics": _metrics(original),
            }
        )
        raw_maps.append(
            {
                "resolution": resolution,
                "original": np.round(original, 6).astype(float).tolist(),
            }
        )

    if enable_inference:
        _populate_pretrain_inference(
            maps=maps,
            raw_maps=raw_maps,
            seed=seed,
            mask_ratio=mask_ratio,
            model_variant=model_variant,
        )

    run_id = f"sc_{int(time.time() * 1000)}"
    result = {
        "status": "ok",
        "run_id": run_id,
        "model_family": "Gudmundson + GenSpectra",
        "model_variant": model_variant,
        "mask_ratio": mask_ratio,
        "mask_unit": "vit_patch",
        "checkpoint_status": _aggregate_checkpoint_status(maps),
        "checkpoint_note": _checkpoint_note(maps),
        "resolutions": selected_resolutions,
        "tx_power_dbm": tx_power or DEFAULT_TX_POWER,
        "frequency_hz": frequency_hz,
        "maps": maps,
    }

    if persist and output_root is not None:
        _persist_metadata(Path(output_root), run_id, result)

    return result


def _fixed_patch_mask(
    rng: np.random.Generator,
    resolution: int,
    *,
    mask_ratio: float,
) -> np.ndarray:
    patch_size = PATCH_SPECS[resolution]
    patch_grid = resolution // patch_size
    total = patch_grid * patch_grid
    visible_count = max(1, min(total - 1, int(round(total * (1 - mask_ratio)))))
    flat = np.zeros(total, dtype=int)
    flat[rng.choice(total, size=visible_count, replace=False)] = 1
    patch_mask = flat.reshape((patch_grid, patch_grid))
    return np.kron(patch_mask, np.ones((patch_size, patch_size), dtype=int))


class _InferenceError(RuntimeError):
    """Raised when neither the warm sidecar nor the cold subprocess can run."""


def _genspectra_sidecar_url() -> str:
    host = os.environ.get("SPECTRUMCLAW_GENSPECTRA_HOST", "127.0.0.1")
    port = os.environ.get("SPECTRUMCLAW_GENSPECTRA_PORT", "8231")
    return os.environ.get("SPECTRUMCLAW_GENSPECTRA_URL", f"http://{host}:{port}")


def _run_inference_request(payload: dict[str, Any], genspectra_python: Path) -> dict[str, Any]:
    """Prefer the warm sidecar (model stays loaded); fall back to a cold subprocess."""
    timeout = int(os.environ.get("SPECTRUMCLAW_GENSPECTRA_TIMEOUT", "300"))
    try:
        return _infer_via_sidecar(payload, timeout)
    except Exception:  # noqa: BLE001 - sidecar down/unreachable -> cold path
        return _infer_via_subprocess(payload, genspectra_python, timeout)


def _infer_via_sidecar(payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    import httpx

    url = _genspectra_sidecar_url().rstrip("/") + "/infer"
    response = httpx.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _infer_via_subprocess(payload: dict[str, Any], genspectra_python: Path, timeout: int) -> dict[str, Any]:
    runner_path = Path(__file__).with_name("genspectra_runner.py")
    try:
        completed = subprocess.run(
            [str(genspectra_python), str(runner_path)],
            input=json.dumps(payload),
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise _InferenceError(f"GenSpectra inference timed out after {exc.timeout}s") from exc
    except OSError as exc:
        raise _InferenceError(str(exc)) from exc

    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip()[-800:]
        raise _InferenceError(message or f"GenSpectra runner exited with {completed.returncode}")

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise _InferenceError(f"invalid GenSpectra runner output: {exc}") from exc


def _populate_pretrain_inference(
    *,
    maps: list[dict[str, Any]],
    raw_maps: list[dict[str, Any]],
    seed: int,
    mask_ratio: float,
    model_variant: str,
) -> None:
    genspectra_root = _genspectra_root()
    genspectra_python = _genspectra_python()

    if not genspectra_root.exists():
        _mark_all_unavailable(
            maps,
            status="pending_checkpoint",
            message=f"GenSpectra root not found: {genspectra_root}",
        )
        return
    if not genspectra_python.exists():
        _mark_all_unavailable(
            maps,
            status="pending_checkpoint",
            message=f"GenSpectra python not found: {genspectra_python}",
        )
        return

    runnable_maps = []
    for raw_map, item in zip(raw_maps, maps, strict=True):
        checkpoint_path = _checkpoint_path(genspectra_root, raw_map["resolution"])
        item["checkpoint_path"] = str(checkpoint_path)
        if checkpoint_path.exists():
            runnable_maps.append(raw_map | {"checkpoint_path": str(checkpoint_path)})
        else:
            item["inference_error"] = f"checkpoint not found: {checkpoint_path}"

    if not runnable_maps:
        return

    payload = {
        "genspectra_root": str(genspectra_root),
        "model_variant": model_variant,
        "seed": seed,
        "mask_ratio": mask_ratio,
        "maps": runnable_maps,
    }

    try:
        runner_result = _run_inference_request(payload, genspectra_python)
    except _InferenceError as exc:
        _mark_resolutions_unavailable(
            maps,
            [item["resolution"] for item in runnable_maps],
            status="failed",
            message=str(exc),
        )
        return

    by_resolution = {item["resolution"]: item for item in runner_result.get("maps", [])}
    for item in maps:
        inference = by_resolution.get(item["resolution"])
        if not inference:
            continue
        if inference.get("status") != "ready":
            item["inference_status"] = inference.get("status", "failed")
            item["inference_error"] = inference.get("error")
            continue
        item["masked"] = inference["masked"]
        item["observed_mask"] = inference["observed_mask"]
        item["reconstruction"] = inference["reconstruction"]
        item["rmse"] = round(float(inference["rmse"]), 4)
        item["inference_status"] = "ready"
        item["inference_error"] = None


def _mark_all_unavailable(
    maps: list[dict[str, Any]],
    *,
    status: str,
    message: str,
) -> None:
    _mark_resolutions_unavailable(
        maps,
        [item["resolution"] for item in maps],
        status=status,
        message=message,
    )


def _mark_resolutions_unavailable(
    maps: list[dict[str, Any]],
    resolutions: list[int],
    *,
    status: str,
    message: str,
) -> None:
    resolution_set = set(resolutions)
    for item in maps:
        if item["resolution"] in resolution_set:
            item["inference_status"] = status
            item["inference_error"] = message


def _aggregate_checkpoint_status(maps: list[dict[str, Any]]) -> str:
    statuses = {item["inference_status"] for item in maps}
    if statuses == {"ready"}:
        return "ready"
    if statuses == {"inference_disabled"}:
        return "inference_disabled"
    if "ready" in statuses:
        return "partial"
    if "failed" in statuses:
        return "failed"
    return "pending_checkpoint"


def _checkpoint_note(maps: list[dict[str, Any]]) -> str:
    status = _aggregate_checkpoint_status(maps)
    if status == "ready":
        return "GenSpectra checkpoints loaded for all requested resolutions."
    if status == "inference_disabled":
        return "GenSpectra inference is disabled for fast preview."
    if status == "partial":
        return "Only part of the requested GenSpectra checkpoints produced reconstruction output."
    errors = [item["inference_error"] for item in maps if item.get("inference_error")]
    if errors:
        return errors[0]
    return "GenSpectra checkpoints are not available in the configured runtime."


def _genspectra_root() -> Path:
    return Path(os.environ.get("SPECTRUMCLAW_GENSPECTRA_ROOT", DEFAULT_GENSPECTRA_ROOT))


def _genspectra_python() -> Path:
    return Path(os.environ.get("SPECTRUMCLAW_GENSPECTRA_PYTHON", DEFAULT_GENSPECTRA_PYTHON))


def _checkpoint_path(genspectra_root: Path, resolution: int) -> Path:
    return (
        genspectra_root
        / "model"
        / "fixed_maskratio_0.75"
        / "pretrain"
        / f"pretrain_GenSpectraLM_{resolution}.pth"
    )


def _matrix_for_json(matrix: np.ndarray) -> list[list[float | None]]:
    clean = np.where(np.isfinite(matrix), np.round(matrix, 4), np.nan)
    rows: list[list[float | None]] = []
    for row in clean.tolist():
        rows.append([None if np.isnan(value) else float(value) for value in row])
    return rows


def _round_matrix(matrix: np.ndarray | None) -> list[list[float]]:
    if matrix is None:
        return []
    return np.round(matrix, 3).astype(float).tolist()


def _metrics(matrix: np.ndarray) -> dict[str, float]:
    return {
        "min_dbm": round(float(np.nanmin(matrix)), 4),
        "max_dbm": round(float(np.nanmax(matrix)), 4),
        "mean_dbm": round(float(np.nanmean(matrix)), 4),
    }


def _persist_metadata(output_root: Path, run_id: str, result: dict[str, Any]) -> None:
    run_dir = output_root / "spectrum_construction" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metadata.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
