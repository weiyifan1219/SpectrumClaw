"""Frequency-planning domain-agent API."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..memory.hooks import track_skill_run
from ..runtime.jobs import get_job_store


router = APIRouter(prefix="/api/frequency-planning")


class InterfererRequest(BaseModel):
    name: str = Field(default="干扰源", max_length=120)
    emitter_type: str = Field(default="unknown", max_length=80)
    frequency_mhz: float = Field(gt=0, le=1_000_000)
    bandwidth_mhz: float = Field(default=20.0, gt=0, le=100_000)
    power_dbm: float = Field(default=20.0, ge=-200, le=100)
    distance_m: float = Field(default=100.0, gt=0, le=10_000_000)
    antenna_gain_dbi: float = Field(default=0.0, ge=-100, le=100)
    activity_factor: float = Field(default=1.0, gt=0, le=1)


class FrequencyPlanningAgentRequest(BaseModel):
    scenario: str = Field(default="", max_length=1000)
    emitter_type: str = Field(default="", max_length=80)
    frequency_band: str = Field(default="", max_length=120)
    tx_power_dbm: float | None = Field(default=None, ge=-200, le=100)
    bandwidth_mhz: float | None = Field(default=None, gt=0, le=100_000)
    coverage_radius_m: float | None = Field(default=None, gt=0, le=10_000_000)
    environment: str = Field(default="", max_length=40)
    service: str = Field(default="", max_length=160)
    region: str = Field(default="", max_length=80)
    country: str = Field(default="", max_length=120)
    noise_figure_db: float | None = Field(default=None, ge=0, le=60)
    antenna_gain_dbi: float | None = Field(default=None, ge=-100, le=100)
    receiver_gain_dbi: float | None = Field(default=None, ge=-100, le=100)
    feeder_loss_db: float | None = Field(default=None, ge=0, le=100)
    minimum_sinr_db: float | None = Field(default=None, ge=-30, le=80)
    guard_band_mhz: float | None = Field(default=None, ge=0, le=10_000)
    coexistence: str = Field(default="", max_length=1000)
    mission_context: str = Field(default="", max_length=4000)
    natural_language_request: str = Field(default="", max_length=8000)
    interferers: list[InterfererRequest] = Field(default_factory=list, max_length=20)
    thinking_enabled: bool = True
    retrieval_mode: str = Field(default="hybrid", max_length=20)
    top_k: int = Field(default=8, ge=3, le=20)


@router.post("/agent/stream")
async def handle_frequency_planning_agent_stream(req: FrequencyPlanningAgentRequest):
    from ..agent.run_events import error as run_error
    from ..agent.run_events import standardize_event

    payload = req.model_dump()
    job_id = get_job_store().start_job(
        kind="frequency_planning_agent",
        title=f"Frequency Agent · {(req.scenario or req.natural_language_request or req.frequency_band)[:48]}",
        prompt_preview=(req.natural_language_request or req.mission_context or req.frequency_band)[:160],
    )

    async def generate():
        try:
            from ..skills.frequency_planning.agent import stream_frequency_planning_agent

            with track_skill_run("frequency_planning_agent", input_data=payload) as run:
                summary = ""
                async for event in stream_frequency_planning_agent(payload):
                    if event.get("type") == "done":
                        analysis = event.get("agent_analysis") or {}
                        confidence = event.get("confidence") or {}
                        summary = (
                            f"availability={analysis.get('availability', 'unknown')}, "
                            f"risk={analysis.get('risk_level', 'unknown')}, "
                            f"confidence={confidence.get('score', 0)}"
                        )
                    standardized = standardize_event(event, source="frequency_planning_agent")
                    recorded = get_job_store().record_event(job_id, standardized)
                    yield f"data: {json.dumps(recorded, ensure_ascii=False)}\n\n"
                run["output_summary"] = summary[:200]
        except Exception as exc:
            event = get_job_store().record_event(
                job_id,
                run_error(str(exc), source="frequency_planning_agent"),
            )
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
