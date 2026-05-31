"""Memory API — overview, items, threads, feedback."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


def _get_service():
    from ..config import get_settings
    from ..memory.service import MemoryService

    settings = get_settings()
    return MemoryService(db_path=settings.memory_db_path), settings


# ── overview ──

@router.get("/api/memory/overview")
async def memory_overview():
    svc, settings = _get_service()
    ov = svc.overview(enabled=settings.memory_enabled)
    # add evolution reports count
    try:
        reports = svc.store.list_reports(limit=100)
        ov.evolution_count = len(reports)
    except Exception:
        pass
    # add skill run stats
    skill_stats = []
    try:
        skill_stats = svc.store.skill_run_stats()
    except Exception:
        pass
    return {
        **ov.model_dump(),
        "skill_stats": skill_stats,
        "reports": [r.model_dump() for r in (reports if 'reports' in dir() else [])],
    }


# ── items ──

@router.get("/api/memory/items")
async def memory_items(
    kind: str | None = Query(None),
    thread_id: str | None = Query(None),
    skill_name: str | None = Query(None),
    tag: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    svc, _ = _get_service()
    items = svc.search_memories(
        kind=kind, thread_id=thread_id,
        skill_name=skill_name, tag=tag,
        limit=limit,
    )
    return {"items": [item.model_dump() for item in items], "total": len(items)}


# ── thread detail ──

@router.get("/api/memory/threads/{thread_id}")
async def memory_thread_detail(thread_id: str):
    svc, _ = _get_service()
    thread = svc.store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    events = svc.store.list_events(thread_id, limit=100)
    items = svc.store.query_items(thread_id=thread_id, limit=50)
    return {
        "thread": thread.model_dump(),
        "events": [e.model_dump() for e in events],
        "items": [it.model_dump() for it in items],
    }


# ── feedback ──

class FeedbackRequest(BaseModel):
    target_type: str
    target_id: str
    rating: int = Field(default=0, ge=-1, le=5)
    comment: str = ""


@router.post("/api/memory/feedback")
async def memory_feedback(body: FeedbackRequest):
    svc, _ = _get_service()
    fb_id = svc.record_feedback(
        target_type=body.target_type,
        target_id=body.target_id,
        rating=body.rating,
        comment=body.comment,
    )
    if fb_id is None:
        raise HTTPException(status_code=500, detail="Failed to record feedback")
    return {"feedback_id": fb_id, "status": "ok"}


# ── skill runs ──

@router.get("/api/memory/skill-runs")
async def memory_skill_runs(
    skill_name: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
):
    svc, _ = _get_service()
    runs = svc.store.list_skill_runs(skill_name=skill_name, limit=limit)
    return {"runs": [r.model_dump() for r in runs]}


# ── evolution reports ──

@router.get("/api/memory/reports")
async def memory_reports(limit: int = Query(10, ge=1, le=50)):
    svc, _ = _get_service()
    reports = svc.store.list_reports(limit=limit)
    return {"reports": [r.model_dump() for r in reports]}
