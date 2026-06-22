from __future__ import annotations

import asyncio
import json

import httpx

from backend.config import get_settings


async def _request(app, method: str, url: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


def _sse_payloads(text: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def test_spectrum_decision_stream_error_uses_run_event_contract(monkeypatch):
    monkeypatch.setenv("SPECTRUMCLAW_MEMORY_ENABLED", "false")
    get_settings.cache_clear()

    async def failing_allocation_stream(**kwargs):
        raise RuntimeError("allocation failed")
        yield {}

    import backend.skills.spectrum_decision.agent as agent_module
    from backend.app import create_app

    monkeypatch.setattr(agent_module, "run_agent_allocation_stream", failing_allocation_stream)
    app = create_app()

    response = asyncio.run(_request(
        app,
        "POST",
        "/api/spectrum-decision/allocate/stream",
        json={"use_agent": True, "user_request": "allocate spectrum"},
    ))

    assert response.status_code == 200
    payloads = _sse_payloads(response.text)
    assert payloads[-1]["type"] == "error"
    assert payloads[-1]["event"] == "error"
    assert payloads[-1]["schema_version"] == "agent-run-v1"
    assert payloads[-1]["source"] == "spectrum_decision"
    assert payloads[-1]["status"] == "error"
    assert payloads[-1]["data"] == "allocation failed"

    get_settings.cache_clear()
