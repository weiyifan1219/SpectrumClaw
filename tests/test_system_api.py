from __future__ import annotations

import asyncio

import httpx


async def _request(app, method: str, url: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


def test_deep_health_exposes_dashboard_contract(monkeypatch):
    monkeypatch.setenv("SPECTRUMCLAW_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("SPECTRUMCLAW_DEEPSEEK_API_KEY", "k")
    monkeypatch.setenv("SPECTRUMCLAW_DEEPSEEK_MODEL", "deepseek-v4-pro")

    from backend.config import get_settings
    from backend.app import create_app
    from backend.api import system as system_api

    get_settings.cache_clear()
    try:
        monkeypatch.setattr(
            system_api,
            "_http_health",
            lambda url: _async_result({"status": "offline", "value": "offline", "detail": "mocked"}),
        )
        app = create_app()

        response = asyncio.run(_request(app, "GET", "/api/system/health/deep"))

        assert response.status_code == 200
        data = response.json()
        assert data["backend"]["status"] == "ok"
        assert data["llm"]["provider"] == "deepseek"
        assert data["llm"]["model"] == "deepseek-v4-pro"
        assert {item["key"] for item in data["summary"]} == {"Backend", "Model", "Knowledge"}
        check_names = {item["name"] for item in data["checks"]}
        assert {"API Service", "LLM Provider", "Memory DB", "RAG Registry", "Vector Store"}.issubset(check_names)
        assert "url" not in data["sidecar"]
    finally:
        get_settings.cache_clear()


def test_artifact_preview_rejects_non_artifact_project_files():
    from backend.app import create_app

    app = create_app()

    response = asyncio.run(_request(app, "GET", "/api/system/artifacts/preview/.env"))

    assert response.status_code == 404


async def _async_result(value):
    return value
