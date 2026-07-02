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


# ── thread list & delete ──

@router.get("/api/memory/threads")
async def memory_threads(limit: int = Query(50, ge=1, le=200)):
    svc, _ = _get_service()
    threads = svc.store.list_threads_with_preview(limit=limit)
    return {"threads": threads}


@router.delete("/api/memory/threads/{thread_id}")
async def memory_delete_thread(thread_id: str):
    svc, _ = _get_service()
    deleted = svc.store.delete_thread(thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"status": "ok"}


@router.post("/api/memory/threads/{thread_id}/touch")
async def memory_touch_thread(thread_id: str):
    """Update last_accessed_at for a thread (called on conversation switch)."""
    svc, _ = _get_service()
    svc.store.touch_thread(thread_id)
    return {"status": "ok"}


@router.post("/api/memory/threads/{thread_id}/summarize")
async def memory_summarize_thread(thread_id: str):
    """Generate an LLM summary for a thread's conversation history."""
    from ..llm.client import chat as llm_chat

    svc, _ = _get_service()
    thread = svc.store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    events = svc.store.list_events(thread_id, limit=100)
    if not events:
        raise HTTPException(status_code=400, detail="Thread has no events to summarize")

    # Build a condensed transcript
    lines: list[str] = []
    for e in events:
        role = "用户" if e.role == "user" else "助手"
        content = (e.content or "").strip()
        if not content:
            continue
        if len(content) > 400:
            content = content[:400] + "…"
        lines.append(f"{role}: {content}")
    transcript = "\n".join(lines[-60:])  # last 60 messages max

    prompt = (
        "你是一个专业的对话总结助手。请根据以下用户与 AI 助手的对话记录，"
        "用一段中文（不超过 200 字）概括对话的核心内容、用户意图和最终结果。"
        "只输出总结文本，不要加任何前缀。\n\n"
        f"{transcript}"
    )

    try:
        reply, _ = await llm_chat(
            [{"role": "user", "content": prompt}],
            thinking_enabled=False,
        )
        summary = reply.strip()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM summary failed: {exc}") from exc

    svc.store.summarize_thread(thread_id, summary)
    return {"status": "ok", "summary": summary}


@router.get("/api/memory/threads/summarize-stale")
async def memory_summarize_stale(hours: int = Query(72, ge=24, le=720)):
    """Auto-summarize threads not accessed in `hours` and without a summary."""
    from ..llm.client import chat as llm_chat

    svc, _ = _get_service()
    stale = svc.store.get_stale_threads(stale_hours=hours)
    if not stale:
        return {"status": "ok", "summarized": 0, "threads": []}

    summarized = []
    for t in stale:
        try:
            events = svc.store.list_events(t["thread_id"], limit=100)
            if not events:
                continue
            lines: list[str] = []
            for e in events:
                role = "用户" if e.role == "user" else "助手"
                content = (e.content or "").strip()
                if not content:
                    continue
                if len(content) > 400:
                    content = content[:400] + "…"
                lines.append(f"{role}: {content}")
            transcript = "\n".join(lines[-60:])

            prompt = (
                "你是一个专业的对话总结助手。请根据以下用户与 AI 助手的对话记录，"
                "用一段中文（不超过 200 字）概括对话的核心内容、用户意图和最终结果。"
                "只输出总结文本，不要加任何前缀。\n\n"
                f"{transcript}"
            )
            reply, _ = await llm_chat(
                [{"role": "user", "content": prompt}],
                thinking_enabled=False,
            )
            summary = reply.strip()
            svc.store.summarize_thread(t["thread_id"], summary)
            summarized.append({"thread_id": t["thread_id"], "title": t["title"], "summary": summary})
        except Exception:
            continue

    return {"status": "ok", "summarized": len(summarized), "threads": summarized}


# ── thread detail (must be AFTER specific routes like summarize-stale) ──

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


@router.post("/api/memory/reflect")
async def memory_reflect(hours: int = Query(168, ge=1, le=720)):
    """Trigger an evolution reflection over the last `hours` of activity.

    Aggregates recent skill runs / feedback / episodic memories, asks the LLM
    to synthesize a report (with rule-based fallback), persists it, and exports
    a JSON copy to data/evolution/.
    """
    from ..memory.reflector import generate_evolution_report

    try:
        report = await generate_evolution_report(hours=hours)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reflection failed: {exc}") from exc
    import json as _json
    try:
        suggestions = _json.loads(report.suggestions_json or "[]")
    except _json.JSONDecodeError:
        suggestions = []
    try:
        metrics = _json.loads(report.metrics_json or "{}")
    except _json.JSONDecodeError:
        metrics = {}
    return {
        "report_id": report.report_id,
        "status": report.status,
        "period": report.period,
        "summary": report.summary,
        "suggestions": suggestions,
        "metrics": metrics,
    }
