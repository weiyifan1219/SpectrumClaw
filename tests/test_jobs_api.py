from __future__ import annotations

import asyncio
import json

import httpx


async def _request(app, method: str, url: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


def test_chat_stream_populates_job_list_and_trace(monkeypatch):
    from backend.runtime.jobs import get_job_store
    import backend.api.chat as chat_api
    from backend.app import create_app

    get_job_store().reset()

    async def fake_stream_chat(*args, **kwargs):
        yield {"type": "stage", "stage": "router", "label": "Route Request"}
        yield {"type": "content", "data": "hello"}
        yield {"type": "done", "data": {"runtime": "langgraph", "thread_id": "th_job"}}

    monkeypatch.setattr(chat_api, "runtime_stream_chat", fake_stream_chat)
    app = create_app()

    response = asyncio.run(
        _request(
            app,
            "POST",
            "/api/chat/stream",
            json={"messages": [{"role": "user", "content": "帮我查频段"}], "thread_id": "th_job"},
        )
    )

    assert response.status_code == 200
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert payloads
    assert all(payload["job_id"].startswith("job_") for payload in payloads)
    job_id = payloads[0]["job_id"]

    jobs_response = asyncio.run(_request(app, "GET", "/api/jobs"))
    assert jobs_response.status_code == 200
    jobs_payload = jobs_response.json()["jobs"]
    assert len(jobs_payload) == 1
    assert jobs_payload[0]["job_id"] == job_id
    assert jobs_payload[0]["status"] == "completed"
    assert jobs_payload[0]["thread_id"] == "th_job"
    assert jobs_payload[0]["event_count"] == 3

    detail_response = asyncio.run(_request(app, "GET", f"/api/jobs/{job_id}?event_limit=10"))
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["job_id"] == job_id
    assert [event["type"] for event in detail_payload["events"]] == ["stage", "content", "done"]
    assert detail_payload["events"][0]["trace_seq"] == 1
    assert detail_payload["events"][-1]["data"]["runtime"] == "langgraph"
