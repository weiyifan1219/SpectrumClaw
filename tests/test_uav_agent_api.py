"""HTTP contracts for the UAV Agent Operations surface."""

from __future__ import annotations

import asyncio

import httpx


async def _request(app, method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_create_draft_and_fetch_run(monkeypatch, tmp_path):
    from backend.api import uav_agent
    from backend.agents.uav_operations.orchestrator import UavOperationsOrchestrator

    class Service:
        _status_reader = staticmethod(lambda: {"runtime": {"state": "running", "manual": {"enabled": False}, "agent_navigation": {"ready": True}}})

        def execute_plan(self, plan):
            return {"ok": True, "events": []}

        def cancel(self):
            return {"ok": True}

    orchestrator = UavOperationsOrchestrator(service=Service(), sandbox_root=tmp_path)
    monkeypatch.setattr(uav_agent, "get_uav_operations_orchestrator", lambda: orchestrator)
    from backend.app import create_app

    app = create_app()
    created = asyncio.run(_request(app, "POST", "/api/uav-agent/runs", json={"intent": "巡检安全周界后返回"}))

    assert created.status_code == 200
    run_id = created.json()["run_id"]
    fetched = asyncio.run(_request(app, "GET", f"/api/uav-agent/runs/{run_id}"))
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "awaiting_approval"


def test_approve_requires_matching_plan_digest(monkeypatch, tmp_path):
    from backend.api import uav_agent
    from backend.agents.uav_operations.orchestrator import UavOperationsOrchestrator

    class Service:
        _status_reader = staticmethod(lambda: {"runtime": {"state": "running", "manual": {"enabled": False}, "agent_navigation": {"ready": True}}})

        def execute_plan(self, plan):
            return {"ok": True, "events": []}

        def cancel(self):
            return {"ok": True}

    orchestrator = UavOperationsOrchestrator(service=Service(), sandbox_root=tmp_path)
    monkeypatch.setattr(uav_agent, "get_uav_operations_orchestrator", lambda: orchestrator)
    from backend.app import create_app

    app = create_app()
    run = asyncio.run(_request(app, "POST", "/api/uav-agent/runs", json={"intent": "巡检安全周界"})).json()
    response = asyncio.run(_request(app, "POST", f"/api/uav-agent/runs/{run['run_id']}/approve", json={"plan_digest": "wrong-digest"}))

    assert response.status_code == 409
    assert response.json()["detail"] == "plan_digest_mismatch"
