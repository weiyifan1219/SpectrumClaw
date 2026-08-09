"""Domain orchestrator for evidence-grounded frequency planning.

This is intentionally more than a prompt wrapper: it resolves planning intent,
runs a deterministic interference tool, retrieves ITU evidence, asks the active
LLM to synthesize a plan, and computes an auditable confidence score.
"""

from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

from ...rag.graph.stream import stream_rag_query
from ...rag.keyword.frequency_matcher import FrequencyRange
from ..interference_analysis.analyzer import analyze_interference


_INTENT_PROMPT = """你是频率规划参数理解器。请从用户描述中抽取工程参数，只返回 JSON，不要 Markdown。
允许字段：scenario, emitter_type, frequency_band, tx_power_dbm, bandwidth_mhz,
coverage_radius_m, environment, service, region, country, minimum_sinr_db,
coexistence, mission_context, interferers。
emitter_type 优先取 base_station, handheld, wifi_ap, iot, radar, broadcast,
satellite_earth_station, telemetry, other；environment 优先取 urban, suburban,
rural, indoor, open, sea, dense_urban。没有明确给出的字段不要猜测，也不要输出。

用户描述：
{request}
"""


async def stream_frequency_planning_agent(request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """Run the complete domain-agent pipeline and emit compatible SSE events."""
    from ...agent.runtime import get_runtime
    from ...config import get_settings

    source = "frequency_planning_agent"
    settings = get_settings()
    provider = settings.provider_profile()

    yield {"type": "stage", "stage": "intent", "label": "Intent Understanding"}
    resolved, intent_meta = await resolve_request(request)
    yield {
        "type": "stage_done",
        "stage": "intent",
        "data": {"mode": intent_meta["mode"], "fields": intent_meta["resolved_fields"]},
    }

    yield {
        "type": "tool_call",
        "data": {
            "tool": "analyze_interference",
            "arguments": _public_engineering_inputs(resolved),
        },
    }
    yield {"type": "stage", "stage": "interference", "label": "Interference Analysis"}
    analysis = analyze_interference(resolved)
    yield {"type": "stage_done", "stage": "interference"}
    yield {
        "type": "tool_result",
        "data": {
            "tool": "analyze_interference",
            "result": analysis,
        },
    }

    evidence_query = build_evidence_query(resolved, analysis)
    request_context = _build_agent_context(resolved, analysis)
    yield {"type": "stage", "stage": "evidence", "label": "Regulatory Evidence"}

    citations: list[dict[str, Any]] = []
    debug: dict[str, Any] = {}
    answer_parts: list[str] = []
    generation_status = "success"
    generation_error = ""
    async for event in stream_rag_query(
        evidence_query,
        profile="frequency_plan",
        thinking_enabled=bool(resolved.get("thinking_enabled", True)),
        request_context=request_context,
    ):
        event_type = event.get("type")
        if event_type == "content":
            answer_parts.append(str(event.get("data", "")))
            yield event
        elif event_type == "done":
            citations = list(event.get("citations") or [])
            debug = dict(event.get("debug") or {})
            generation_status = str(event.get("generation_status") or "success")
            generation_error = str(event.get("generation_error") or "")
        else:
            yield event

    yield {"type": "stage_done", "stage": "evidence", "data": {"citations": len(citations)}}
    generation_succeeded = generation_status == "success"
    confidence = calculate_confidence(
        resolved,
        analysis,
        citations,
        generation_succeeded=generation_succeeded,
    )
    yield {
        "type": "done",
        "citations": citations,
        "debug": debug,
        "agent_analysis": analysis,
        "confidence": confidence,
        "resolved_request": _public_engineering_inputs(resolved),
        "agent": {
            "kind": "frequency_planning_agent",
            "runtime": "domain_orchestrator",
            "platform_runtime": get_runtime(),
            "configured": provider.configured,
            "provider": provider.provider,
            "model": provider.model if provider.configured else "",
            "tools": ["analyze_interference", "itu_rag_frequency_plan"],
            "answer_generated": bool("".join(answer_parts).strip()),
            "llm_succeeded": generation_succeeded,
            "generation_status": generation_status,
            "generation_error": generation_error,
            "intent_mode": intent_meta["mode"],
            "source": source,
        },
    }


async def resolve_request(request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge explicit fields with LLM/fallback extraction from natural language."""
    resolved = dict(request)
    natural_language = str(request.get("natural_language_request") or "").strip()
    mode = "structured"
    extracted: dict[str, Any] = {}

    if natural_language:
        mode = "natural_language"
        extracted.update(_fallback_extract(natural_language))
        try:
            from ...config import get_settings
            from ...llm.client import chat

            provider = get_settings().provider_profile()
            if provider.configured:
                reply, _ = await chat(
                    [{"role": "user", "content": _INTENT_PROMPT.format(request=natural_language)}],
                    provider_override=provider.provider,
                    model_override=provider.model,
                    thinking_enabled=False,
                    tool_names=[],
                )
                extracted.update(_extract_json_object(reply))
                mode = "llm_intent"
        except Exception:
            mode = "fallback_intent"

        for key, value in extracted.items():
            if value not in (None, "", [], {}):
                resolved[key] = value
        resolved["mission_context"] = str(resolved.get("mission_context") or natural_language)
        resolved["scenario"] = str(resolved.get("scenario") or natural_language[:80])

    return resolved, {
        "mode": mode,
        "resolved_fields": sorted(key for key, value in resolved.items() if value not in (None, "", [], {})),
    }


def build_evidence_query(request: dict[str, Any], analysis: dict[str, Any]) -> str:
    """Build a retrieval-focused query while preserving the user's planning facts."""
    findings = ", ".join(
        str(item.get("type")) for item in (analysis.get("interference_findings") or [])[:4]
        if item.get("type")
    ) or "相邻频段、同频与带外干扰"
    parts = [
        str(request.get("frequency_band") or "目标频段"),
        str(request.get("region") or "ITU 区域未指定"),
        str(request.get("country") or ""),
        str(request.get("service") or "无线电业务"),
        "频率划分 主要业务 次要业务 脚注 协调 保护标准 共存约束 干扰限值",
        f"场景 {request.get('scenario') or '未指定'}",
        f"发射源 {request.get('emitter_type') or '未指定'}",
        f"发射功率 {request.get('tx_power_dbm') if request.get('tx_power_dbm') is not None else '未指定'} dBm",
        f"干扰类型 {findings}",
    ]
    coexistence = str(request.get("coexistence") or "").strip()
    if coexistence:
        parts.append(f"需与 {coexistence} 共存")
    return "；".join(part for part in parts if part)


def calculate_confidence(
    request: dict[str, Any],
    analysis: dict[str, Any],
    citations: list[dict[str, Any]],
    *,
    generation_succeeded: bool = True,
) -> dict[str, Any]:
    """Calculate evidence-aware confidence; never let the LLM self-score it."""
    required_fields = (
        "frequency_band", "emitter_type", "tx_power_dbm", "bandwidth_mhz",
        "coverage_radius_m", "environment", "service", "region",
    )
    present = sum(request.get(field) not in (None, "", [], {}) for field in required_fields)
    input_completeness = present / len(required_fields)
    if FrequencyRange.parse(str(request.get("frequency_band") or "")) is None:
        input_completeness *= 0.45

    relevance_values = []
    for citation in citations:
        try:
            value = float(citation.get("relevance", citation.get("score", 0)) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            relevance_values.append(value)
    citation_depth = min(1.0, len(citations) / 3.0)
    relevance = min(1.0, max(relevance_values, default=0.0) / 0.8)
    evidence_coverage = 0.55 * citation_depth + 0.45 * relevance
    retrieval_backends = {
        str(citation.get("retrieval_backend") or "primary") for citation in citations
    }
    parsed_cache_only = bool(citations) and retrieval_backends == {"parsed_cache_lexical"}
    retrieval_quality = 0.72 if parsed_cache_only else 1.0
    evidence_coverage *= retrieval_quality

    model_applicability = 0.75 if analysis.get("link_budget") else 0.2
    if str(request.get("environment") or "") in {"indoor", "dense_urban"}:
        model_applicability -= 0.12
    if str(request.get("emitter_type") or "") in {"radar", "satellite_earth_station"}:
        model_applicability -= 0.10
    model_applicability = max(0.0, min(1.0, model_applicability))

    margin = abs(float((analysis.get("link_budget") or {}).get("sinr_margin_db", 0.0) or 0.0))
    decision_margin = min(1.0, margin / 10.0)
    model_synthesis = 1.0 if generation_succeeded else 0.0
    score = (
        0.25 * input_completeness
        + 0.30 * evidence_coverage
        + 0.15 * model_applicability
        + 0.10 * decision_margin
        + 0.20 * model_synthesis
    )
    if not citations:
        score = min(score, 0.58)
    if not generation_succeeded:
        score = min(score, 0.58)
    if parsed_cache_only:
        score = min(score, 0.79)
    score = round(max(0.0, min(1.0, score)), 2)
    level = "high" if score >= 0.80 else "medium" if score >= 0.60 else "low"

    explanations = []
    explanations.append(f"关键输入完整度 {input_completeness:.0%}")
    explanations.append(f"知识证据覆盖 {evidence_coverage:.0%}（{len(citations)} 条引用）")
    explanations.append(f"简化工程模型适用度 {model_applicability:.0%}")
    explanations.append(f"决策裕量稳定度 {decision_margin:.0%}")
    explanations.append(f"模型综合状态 {'成功' if generation_succeeded else '失败'}")
    if parsed_cache_only:
        explanations.append("标准混合索引不可用，本次证据来自 parsed cache 词法兜底")
    if not citations:
        explanations.append("未获得可引用的 ITU 证据，置信度已封顶")
    if not generation_succeeded:
        explanations.append("模型综合失败，置信度已降级")
    return {
        "score": score,
        "percentage": int(round(score * 100)),
        "level": level,
        "factors": {
            "input_completeness": round(input_completeness, 2),
            "evidence_coverage": round(evidence_coverage, 2),
            "model_applicability": round(model_applicability, 2),
            "decision_margin": round(decision_margin, 2),
            "model_synthesis": model_synthesis,
            "retrieval_quality": retrieval_quality,
        },
        "explanation": "；".join(explanations) + "。",
    }


def _build_agent_context(request: dict[str, Any], analysis: dict[str, Any]) -> str:
    context = {
        "输入参数": _public_engineering_inputs(request),
        "确定性工程分析": analysis,
    }
    return (
        "## 领域智能体补充上下文\n"
        "以下内容来自透明的确定性工程计算，不是 ITU 法规原文。法规、业务划分、脚注与保护标准必须由检索证据支持；"
        "链路预算、干扰类型、SINR 和候选信道可引用本计算，但必须标注模型假设与局限。\n\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )


def _public_engineering_inputs(request: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "scenario", "emitter_type", "frequency_band", "tx_power_dbm", "bandwidth_mhz",
        "coverage_radius_m", "environment", "service", "region", "country",
        "noise_figure_db", "antenna_gain_dbi", "receiver_gain_dbi", "feeder_loss_db",
        "minimum_sinr_db", "guard_band_mhz", "coexistence", "mission_context", "interferers",
    )
    return {key: request.get(key) for key in keys if request.get(key) not in (None, "", [], {})}


def _fallback_extract(text: str) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    range_match = re.search(
        r"(\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?\s*(?:GHz|MHz|kHz|Hz))",
        text,
        re.IGNORECASE,
    )
    single_match = re.search(r"(\d+(?:\.\d+)?\s*(?:GHz|MHz|kHz|Hz))", text, re.IGNORECASE)
    if range_match or single_match:
        extracted["frequency_band"] = (range_match or single_match).group(1)
    power = re.search(r"(?:功率|发射功率)?\s*(\d+(?:\.\d+)?)\s*dBm", text, re.IGNORECASE)
    if power:
        extracted["tx_power_dbm"] = float(power.group(1))
    bandwidth = re.search(r"(?:带宽|bandwidth)\s*(?:为|约|=|:)?\s*(\d+(?:\.\d+)?)\s*MHz", text, re.IGNORECASE)
    if bandwidth:
        extracted["bandwidth_mhz"] = float(bandwidth.group(1))
    distance = re.search(r"(?:覆盖|半径|距离)\s*(?:为|约|=|:)?\s*(\d+(?:\.\d+)?)\s*(km|公里|m|米)", text, re.IGNORECASE)
    if distance:
        value = float(distance.group(1))
        extracted["coverage_radius_m"] = value * 1000.0 if distance.group(2).lower() in {"km", "公里"} else value
    keyword_maps = {
        "environment": {
            "dense_urban": ("密集城区", "高楼城区"), "urban": ("城市", "城区"),
            "suburban": ("郊区",), "rural": ("农村", "乡村"), "indoor": ("室内",),
            "sea": ("海上", "海面"), "open": ("开阔",),
        },
        "emitter_type": {
            "radar": ("雷达",), "wifi_ap": ("wifi", "wi-fi", "热点"),
            "base_station": ("基站",), "handheld": ("手持", "对讲机"),
            "satellite_earth_station": ("卫星地球站", "卫星地面站"),
            "broadcast": ("广播",), "iot": ("物联网", "iot"), "telemetry": ("遥测",),
        },
    }
    lowered = text.lower()
    for field, mapping in keyword_maps.items():
        for value, keywords in mapping.items():
            if any(keyword in lowered for keyword in keywords):
                extracted[field] = value
                break
    return extracted


def _extract_json_object(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(text[start:end + 1])
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
