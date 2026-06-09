"""Spectrum Construction API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..rag.paths import PROJECT_ROOT
from ..memory.hooks import track_skill_run
from ..skills.spectrum_construction.generator import (
    DEFAULT_MASK_RATIO,
    DEFAULT_MODEL_VARIANT,
    DEFAULT_RESOLUTIONS,
    build_multi_resolution_preview,
)
from ..skills.spectrum_construction.uav_rem import build_uav_rem_overview

router = APIRouter(prefix="/api/spectrum-construction")


class SpectrumConstructionRequest(BaseModel):
    seed: int = Field(default=0, ge=0)
    resolutions: list[int] = Field(default_factory=lambda: DEFAULT_RESOLUTIONS.copy())
    mask_ratio: float = Field(default=DEFAULT_MASK_RATIO, gt=0, lt=1)
    model_variant: str = DEFAULT_MODEL_VARIANT
    enable_inference: bool = False
    tx_power_dbm: list[float] = Field(default_factory=lambda: [14.0, 20.0], min_length=1, max_length=4)
    frequency_hz: float = Field(default=1.4e9, gt=0)
    persist: bool = False


class UavRemOverviewRequest(BaseModel):
    scene_id: int = Field(default=148, ge=0)
    height_layer: int = Field(default=2, ge=0)
    method: str = "abr"


@router.post("/generate")
def handle_generate(req: SpectrumConstructionRequest):
    try:
        with track_skill_run("spectrum_construction", input_data=req.model_dump()) as run:
            result = build_multi_resolution_preview(
                seed=req.seed,
                resolutions=req.resolutions,
                mask_ratio=req.mask_ratio,
                model_variant=req.model_variant,
                enable_inference=req.enable_inference,
                tx_power=req.tx_power_dbm,
                n_tx=len(req.tx_power_dbm),
                frequency_hz=req.frequency_hz,
                output_root=PROJECT_ROOT / "outputs",
                persist=req.persist,
            )
            run["output_summary"] = (
                f"variant={req.model_variant}, resolutions={req.resolutions}, "
                f"infer={req.enable_inference}, n_tx={len(req.tx_power_dbm)}"
            )[:200]
            return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/uav-rem/overview")
def handle_uav_rem_overview(req: UavRemOverviewRequest):
    try:
        with track_skill_run("uav_rem_overview", input_data=req.model_dump()) as run:
            result = build_uav_rem_overview(
                scene_id=req.scene_id,
                height_layer=req.height_layer,
                method=req.method,
            )
            run["output_summary"] = (
                f"scene={req.scene_id}, layer={req.height_layer}, method={req.method}"
            )[:200]
            return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
