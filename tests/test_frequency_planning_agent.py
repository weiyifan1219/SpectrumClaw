from __future__ import annotations

import asyncio
import json

import httpx

from backend.config import get_settings


def _request(**overrides):
    request = {
        "scenario": "城市应急通信",
        "emitter_type": "base_station",
        "frequency_band": "2300-2400 MHz",
        "tx_power_dbm": 30.0,
        "bandwidth_mhz": 20.0,
        "coverage_radius_m": 500.0,
        "environment": "urban",
        "service": "Land Mobile",
        "region": "Region 3",
        "country": "中国",
        "noise_figure_db": 7.0,
        "antenna_gain_dbi": 8.0,
        "feeder_loss_db": 2.0,
        "interferers": [],
        "thinking_enabled": True,
    }
    request.update(overrides)
    return request


def test_agent_evidence_query_carries_scene_emitter_power_and_band():
    from backend.skills.frequency_planning.agent import build_evidence_query
    from backend.skills.interference_analysis.analyzer import analyze_interference

    request = _request()
    analysis = analyze_interference(request)
    query = build_evidence_query(request, analysis)

    assert "城市应急通信" in query
    assert "base_station" in query
    assert "30" in query
    assert "2300-2400 MHz" in query
    assert "干扰" in query
    assert "Region 3" in query


def test_confidence_increases_with_cited_evidence():
    from backend.skills.frequency_planning.agent import calculate_confidence
    from backend.skills.interference_analysis.analyzer import analyze_interference

    request = _request()
    analysis = analyze_interference(request)
    without_evidence = calculate_confidence(request, analysis, [])
    with_evidence = calculate_confidence(request, analysis, [
        {"source": "R-REC-SM.0001", "relevance": 0.82},
        {"source": "R-REC-M.0002", "relevance": 0.75},
        {"source": "R-REP-SM.0003", "relevance": 0.68},
    ])

    assert with_evidence["score"] > without_evidence["score"]
    assert with_evidence["factors"]["evidence_coverage"] > without_evidence["factors"]["evidence_coverage"]
    assert with_evidence["level"] in {"medium", "high"}
    assert with_evidence["explanation"]


def test_confidence_is_capped_when_llm_synthesis_fails():
    from backend.skills.frequency_planning.agent import calculate_confidence
    from backend.skills.interference_analysis.analyzer import analyze_interference

    request = _request()
    analysis = analyze_interference(request)
    citations = [{"source": f"R-REC-{index}", "relevance": 0.9} for index in range(4)]

    successful = calculate_confidence(request, analysis, citations, generation_succeeded=True)
    failed = calculate_confidence(request, analysis, citations, generation_succeeded=False)

    assert failed["score"] < successful["score"]
    assert failed["score"] <= 0.58
    assert failed["level"] == "low"
    assert failed["factors"]["model_synthesis"] == 0.0
    assert "模型综合失败" in failed["explanation"]


def test_confidence_marks_parsed_cache_only_evidence_as_degraded():
    from backend.skills.frequency_planning.agent import calculate_confidence
    from backend.skills.interference_analysis.analyzer import analyze_interference

    request = _request()
    analysis = analyze_interference(request)
    citations = [
        {"source": f"R-REC-{index}", "relevance": 0.9, "retrieval_backend": "parsed_cache_lexical"}
        for index in range(4)
    ]

    confidence = calculate_confidence(request, analysis, citations, generation_succeeded=True)

    assert confidence["score"] <= 0.79
    assert confidence["level"] == "medium"
    assert confidence["factors"]["retrieval_quality"] < 1.0
    assert "词法兜底" in confidence["explanation"]


def test_frequency_agent_stream_combines_engineering_analysis_and_rag(monkeypatch):
    import backend.skills.frequency_planning.agent as agent_module

    async def fake_rag_stream(question, profile, thinking_enabled, request_context=""):
        assert profile == "frequency_plan"
        assert "城市应急通信" in question
        assert "确定性工程分析" in request_context
        yield {"type": "stage", "stage": "query_analysis", "label": "Query Analysis"}
        yield {"type": "stage_done", "stage": "query_analysis"}
        yield {"type": "content", "data": "**结论：** 可在协调后使用。\n"}
        yield {
            "type": "done",
            "citations": [{"source": "R-REC-SM.0001", "page": 3, "relevance": 0.82}],
            "debug": {"retrieved_blocks": [{"text": "evidence", "metadata": {}}]},
        }

    monkeypatch.setattr(agent_module, "stream_rag_query", fake_rag_stream)

    events = asyncio.run(_collect(agent_module.stream_frequency_planning_agent(_request())))

    assert any(event["type"] == "tool_result" and event["data"]["tool"] == "analyze_interference" for event in events)
    done = events[-1]
    assert done["type"] == "done"
    assert done["agent_analysis"]["availability"] in {"available", "conditional", "unavailable"}
    assert done["confidence"]["score"] > 0
    assert done["agent"]["kind"] == "frequency_planning_agent"
    assert done["citations"][0]["source"] == "R-REC-SM.0001"


def test_frequency_agent_api_uses_standard_stream_contract(monkeypatch):
    monkeypatch.setenv("SPECTRUMCLAW_MEMORY_ENABLED", "false")
    get_settings.cache_clear()

    async def fake_agent_stream(request):
        assert request["interferers"][0]["frequency_mhz"] == 2410.0
        yield {"type": "stage", "stage": "intent", "label": "Intent Understanding"}
        yield {
            "type": "done",
            "citations": [],
            "debug": {},
            "agent_analysis": {"availability": "conditional"},
            "confidence": {"score": 0.61, "level": "medium", "factors": {}, "explanation": "证据有限"},
            "agent": {"kind": "frequency_planning_agent", "configured": True, "model": "test-model"},
        }

    import backend.skills.frequency_planning.agent as agent_module
    from backend.app import create_app

    monkeypatch.setattr(agent_module, "stream_frequency_planning_agent", fake_agent_stream)
    app = create_app()

    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/frequency-planning/agent/stream", json=_request(interferers=[{
                "name": "邻近专网基站",
                "frequency_mhz": 2410.0,
                "bandwidth_mhz": 20.0,
                "power_dbm": 33.0,
                "distance_m": 800.0,
            }]))

    response = asyncio.run(request())
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]

    assert response.status_code == 200
    assert payloads[-1]["type"] == "done"
    assert payloads[-1]["schema_version"] == "agent-run-v1"
    assert payloads[-1]["source"] == "frequency_planning_agent"
    assert payloads[-1]["agent_analysis"]["availability"] == "conditional"

    get_settings.cache_clear()


async def _collect(stream):
    return [event async for event in stream]
