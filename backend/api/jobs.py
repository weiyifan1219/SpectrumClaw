from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..runtime.jobs import get_job_store

router = APIRouter(prefix="/api/jobs")


@router.get("")
async def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
):
    return {"jobs": get_job_store().list_jobs(limit=limit, status=status)}


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    event_limit: int = Query(100, ge=1, le=500),
):
    payload = get_job_store().get_job(job_id, event_limit=event_limit)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return payload
