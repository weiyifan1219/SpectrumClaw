"""Natural-language UAV task drafts, approval and public execution events."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agents.uav_operations import get_uav_operations_orchestrator
from ..skills.uav_spectrum_sim.templates import list_templates


router = APIRouter(prefix="/api/uav-agent")


class DraftRequest(BaseModel):
    intent: str = Field(min_length=2, max_length=800)


class ApprovalRequest(BaseModel):
    plan_digest: str = Field(min_length=8, max_length=128)


@router.get("/templates")
def templates() -> dict:
    return {"templates": list_templates()}


@router.post("/runs")
def create_run(request: DraftRequest) -> dict:
    try:
        return get_uav_operations_orchestrator().create_draft(request.intent)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = get_uav_operations_orchestrator().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="uav_run_not_found")
    return run


@router.post("/runs/{run_id}/approve")
def approve_run(run_id: str, request: ApprovalRequest) -> dict:
    run = get_uav_operations_orchestrator().start_approval(run_id, request.plan_digest)
    if run.get("error_code") == "run_not_found":
        raise HTTPException(status_code=404, detail="uav_run_not_found")
    if run.get("error_code") == "plan_digest_mismatch":
        raise HTTPException(status_code=409, detail="plan_digest_mismatch")
    return run


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict:
    run = get_uav_operations_orchestrator().cancel(run_id)
    if run.get("error_code") == "run_not_found":
        raise HTTPException(status_code=404, detail="uav_run_not_found")
    return run


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str):
    orchestrator = get_uav_operations_orchestrator()
    if orchestrator.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="uav_run_not_found")

    async def generate():
        cursor = 0
        idle_rounds = 0
        while idle_rounds < 150:
            run = orchestrator.get_run(run_id)
            if run is None:
                return
            events = run.get("events", [])
            for event in events[cursor:]:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            cursor = len(events)
            if run.get("status") in {"awaiting_approval", "rejected", "completed", "failed", "cancelled", "interrupted"}:
                yield f"data: {json.dumps({'event_type': 'run_state', 'summary': run.get('summary', ''), 'status': run.get('status'), 'run_id': run_id, 'trace_id': run.get('trace_id')}, ensure_ascii=False)}\n\n"
                return
            idle_rounds += 1
            await asyncio.sleep(0.2)

    return StreamingResponse(generate(), media_type="text/event-stream")
