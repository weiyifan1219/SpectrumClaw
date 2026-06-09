"""Evolution reflector — aggregate recent memory data and synthesize an
evolution report (summary + improvement suggestions) via the LLM.

Triggered manually through POST /api/memory/reflect. Best-effort by design:
if the LLM call or JSON parsing fails, a rule-based fallback report is still
produced from the aggregated metrics, so reflection always yields a report.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import EvolutionReport
from .service import MemoryService


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _aggregate(mem: MemoryService, cutoff: datetime) -> dict[str, Any]:
    """Pull recent skill runs, feedback, and episodic memories; compute metrics."""
    store = mem.store

    skill_runs = store.list_skill_runs(limit=200)
    recent_runs = [r for r in skill_runs if (_parse_ts(r.created_at) or _now()) >= cutoff]

    feedback = store.list_feedback(limit=100)
    recent_fb = [f for f in feedback if (_parse_ts(f.created_at) or _now()) >= cutoff]

    episodic = store.query_items(kind="episodic", limit=100)
    recent_epi = [e for e in episodic if (_parse_ts(e.created_at) or _now()) >= cutoff]

    # per-skill breakdown
    per_skill: dict[str, dict[str, Any]] = {}
    for r in recent_runs:
        s = per_skill.setdefault(r.skill_name, {"total": 0, "success": 0, "failed": 0, "latency_sum": 0, "errors": []})
        s["total"] += 1
        if r.status == "success":
            s["success"] += 1
        else:
            s["failed"] += 1
            if r.error:
                s["errors"].append(r.error[:160])
        s["latency_sum"] += r.latency_ms or 0
    for s in per_skill.values():
        s["success_rate"] = round(s["success"] / s["total"], 3) if s["total"] else 0.0
        s["avg_latency_ms"] = round(s["latency_sum"] / s["total"], 1) if s["total"] else 0.0
        s.pop("latency_sum", None)

    total_runs = len(recent_runs)
    total_success = sum(1 for r in recent_runs if r.status == "success")
    ratings = [f.rating for f in recent_fb if f.rating]
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0.0
    low_comments = [f.comment[:160] for f in recent_fb if f.rating and f.rating <= 2 and f.comment]
    epi_topics = [e.text[:100] for e in recent_epi[:15]]

    metrics = {
        "skill_runs": total_runs,
        "success_rate": round(total_success / total_runs, 3) if total_runs else 0.0,
        "avg_rating": avg_rating,
        "feedback_count": len(recent_fb),
        "episodic_count": len(recent_epi),
        "per_skill": per_skill,
    }
    raw = {
        "low_rating_comments": low_comments,
        "episodic_topics": epi_topics,
        "failed_examples": [
            {"skill": r.skill_name, "error": r.error[:160]}
            for r in recent_runs if r.status != "success" and r.error
        ][:10],
    }
    return {"metrics": metrics, "raw": raw}


async def _llm_synthesize(period: str, metrics: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any] | None:
    """Ask the LLM to summarize the period and propose improvements.

    Returns {"summary": str, "suggestions": [{"priority","action"}]} or None on failure.
    """
    try:
        from ..llm.client import chat

        payload = {
            "时间窗口": period,
            "指标": metrics,
            "低分反馈": raw.get("low_rating_comments", []),
            "失败案例": raw.get("failed_examples", []),
            "近期查询主题": raw.get("episodic_topics", []),
        }
        system = (
            "你是 SpectrumClaw 频谱智能体的自我进化分析模块。"
            "根据给定的运行指标、技能成败、用户反馈，撰写一份简洁的中文进化报告。"
            "必须严格输出 JSON，格式为 "
            '{"summary": "一段话总结本周期系统表现与问题", '
            '"suggestions": [{"priority": "high|medium|low", "action": "具体改进建议"}]}。'
            "summary 控制在 120 字内，suggestions 给 2-4 条，按优先级排序，针对失败技能和低分反馈提出可执行建议。"
            "不要输出 JSON 以外的任何内容。"
        )
        user = "以下是本周期的聚合数据：\n" + json.dumps(payload, ensure_ascii=False, indent=2)

        reply, _meta = await chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        parsed = _extract_json(reply)
        if parsed and isinstance(parsed.get("summary"), str):
            sugg = parsed.get("suggestions", [])
            if not isinstance(sugg, list):
                sugg = []
            clean = []
            for s in sugg:
                if isinstance(s, dict) and s.get("action"):
                    clean.append({
                        "priority": str(s.get("priority", "medium")).lower(),
                        "action": str(s.get("action"))[:240],
                    })
            return {"summary": parsed["summary"][:400], "suggestions": clean}
    except Exception:
        pass
    return None


def _extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort extraction of a JSON object from an LLM reply."""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    # strip markdown fences / surrounding prose
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None


def _fallback_report(metrics: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """Rule-based report when the LLM is unavailable or returns bad JSON."""
    runs = metrics.get("skill_runs", 0)
    sr = metrics.get("success_rate", 0.0)
    fb = metrics.get("feedback_count", 0)
    epi = metrics.get("episodic_count", 0)
    summary = (
        f"本周期共记录 {runs} 次技能调用，成功率 {round(sr * 100)}%，"
        f"{epi} 条情景记忆、{fb} 条用户反馈。"
    )
    suggestions: list[dict[str, Any]] = []
    per_skill = metrics.get("per_skill", {})
    for name, s in sorted(per_skill.items(), key=lambda kv: kv[1].get("success_rate", 1.0)):
        if s.get("failed", 0) > 0:
            suggestions.append({
                "priority": "high" if s.get("success_rate", 1.0) < 0.5 else "medium",
                "action": f"技能 {name} 有 {s['failed']}/{s['total']} 次失败，建议排查错误并加固。",
            })
    if metrics.get("avg_rating", 0) and metrics["avg_rating"] < 3:
        suggestions.append({
            "priority": "high",
            "action": f"平均评分偏低（{metrics['avg_rating']}），需检查低分反馈并改进回答质量。",
        })
    if not suggestions:
        suggestions.append({"priority": "low", "action": "系统运行平稳，建议持续积累数据以支撑下一轮进化分析。"})
    return {"summary": summary, "suggestions": suggestions[:4]}


def _export_json(report: EvolutionReport, metrics: dict[str, Any], raw: dict[str, Any]) -> str:
    """Write the full report (incl. raw aggregates) to data/evolution/<id>.json."""
    try:
        from ..config import get_settings

        ev_dir = Path(get_settings().evolution_dir)
        ev_dir.mkdir(parents=True, exist_ok=True)
        out = ev_dir / f"{report.report_id}.json"
        payload = {
            "report_id": report.report_id,
            "period": report.period,
            "summary": report.summary,
            "status": report.status,
            "created_at": report.created_at,
            "metrics": metrics,
            "suggestions": json.loads(report.suggestions_json or "[]"),
            "raw_aggregates": raw,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(out)
    except Exception:
        return ""


async def generate_evolution_report(hours: int = 168, db_path: str | None = None) -> EvolutionReport:
    """Aggregate the last `hours` of activity, synthesize a report via LLM
    (with rule-based fallback), persist it to SQLite, and export JSON.

    Always returns an EvolutionReport (never raises for empty data).
    """
    from ..config import get_settings

    settings = get_settings()
    mem = MemoryService(db_path=db_path or settings.memory_db_path)

    now = _now()
    cutoff = now - timedelta(hours=hours)
    period = f"{cutoff:%Y-%m-%d %H:%M} ~ {now:%Y-%m-%d %H:%M}"

    agg = _aggregate(mem, cutoff)
    metrics, raw = agg["metrics"], agg["raw"]

    synth = await _llm_synthesize(period, metrics, raw)
    if synth is None:
        synth = _fallback_report(metrics, raw)

    report = EvolutionReport(
        report_id=f"rpt_{uuid.uuid4().hex[:12]}",
        period=period,
        summary=synth["summary"],
        metrics_json=json.dumps(metrics, ensure_ascii=False),
        suggestions_json=json.dumps(synth["suggestions"], ensure_ascii=False),
        status="pending",
    )
    try:
        mem.store.insert_report(report)
    except Exception:
        pass

    _export_json(report, metrics, raw)
    return report
