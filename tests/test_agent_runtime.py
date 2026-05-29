from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from backend.config import get_settings


async def _collect_events(aiter):
    return [event async for event in aiter]


def _configure_runtime_env(monkeypatch):
    for key in (
        "SPECTRUMCLAW_LLM_PROVIDER",
        "SPECTRUMCLAW_DEEPSEEK_API_KEY",
        "DEEPSEEK_API_KEY",
        "SPECTRUMCLAW_DEEPSEEK_MODEL",
        "DEEPSEEK_MODEL",
        "SPECTRUMCLAW_AGENT_RUNTIME",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SPECTRUMCLAW_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("SPECTRUMCLAW_AGENT_RUNTIME", "langgraph")
    get_settings.cache_clear()


def test_agent_runtime_env_is_read(monkeypatch):
    _configure_runtime_env(monkeypatch)

    from backend.agent.runtime import get_runtime

    assert get_runtime() == "langgraph"


def test_start_backend_exports_runtime_inside_conda_run():
    script = (Path(__file__).resolve().parents[1] / "scripts" / "local" / "start_backend.sh").read_text()

    assert 'env SPECTRUMCLAW_AGENT_RUNTIME="$AGENT_RUNTIME"' in script
    assert "conda env config vars set" not in script


def test_stream_endpoint_uses_agent_runtime(monkeypatch):
    _configure_runtime_env(monkeypatch)

    async def fake_stream_chat(*args, **kwargs):
        yield {"type": "thinking", "data": "runtime marker"}
        yield {"type": "content", "data": "ok"}
        yield {"type": "done", "data": {"runtime": "langgraph"}}

    import backend.api.chat as chat_api

    monkeypatch.setattr(chat_api, "runtime_stream_chat", fake_stream_chat)

    from backend.app import create_app

    app = create_app()

    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/chat/stream",
                json={"messages": [{"role": "user", "content": "你好"}]},
            )

    response = asyncio.run(request())
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]

    assert response.status_code == 200
    assert [p["type"] for p in payloads] == ["thinking", "content", "done"]
    assert payloads[-1]["data"]["runtime"] == "langgraph"


def test_langgraph_stream_plain_tool_and_rag_paths(monkeypatch):
    _configure_runtime_env(monkeypatch)

    async def fake_chat(messages, **kwargs):
        if any("[工具结果]" in str(m.get("content", "")) for m in messages):
            return "工具回答", {"provider": "deepseek", "api_type": "openai_compatible", "tool_rounds": 0}
        if any("ITU 知识库" in str(m.get("content", "")) for m in messages):
            return "知识库回答", {"provider": "deepseek", "api_type": "openai_compatible", "tool_rounds": 0}
        return "普通回答", {"provider": "deepseek", "api_type": "openai_compatible", "tool_rounds": 0}

    def fake_search(query, top_k=5):
        return [{"source": "R-REC-M.0001", "score": 0.88, "text": "ITU 频谱测试内容"}]

    import backend.llm.client as llm_client
    import backend.knowledge.retrieve as retrieve
    import backend.agent.graph as graph_module
    from backend.agent.runtime import stream_chat_langgraph

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    monkeypatch.setattr(retrieve, "search", fake_search)
    graph_module._graph = None

    cases = [
        ("你好", "普通回答", ["router", "llm_answer", "finalizer"]),
        ("现在几点？", "工具回答", ["router", "tool_executor", "llm_answer", "finalizer"]),
        ("查询 ITU 2.4GHz 频谱规定", "知识库回答", ["router", "rag_search", "llm_answer", "finalizer"]),
    ]

    async def run_cases():
        for prompt, expected_content, expected_nodes in cases:
            graph_module._graph = None
            events = await _collect_events(stream_chat_langgraph([{"role": "user", "content": prompt}]))
            event_types = [event["type"] for event in events]
            done_event = events[-1]

            assert event_types[0] == "thinking"
            assert event_types[-2:] == ["content", "done"]
            assert events[-2]["data"] == expected_content
            assert done_event["data"]["graph_nodes"] == expected_nodes

    asyncio.run(run_cases())
