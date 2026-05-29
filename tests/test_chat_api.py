from __future__ import annotations

import asyncio

import httpx

from backend.config import Settings, get_settings
from backend.llm.client import _openai_endpoint, strip_thinking


def _reload_app_without_env(monkeypatch):
    for key in (
        "SPECTRUMCLAW_LLM_PROVIDER",
        "SPECTRUMCLAW_LLM_BASE_URL",
        "SPECTRUMCLAW_LLM_API_KEY",
        "SPECTRUMCLAW_LLM_MODEL",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir("/")
    get_settings.cache_clear()

    from backend.app import create_app

    return create_app()


async def _request(app, method: str, url: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


def test_health_returns_ok(monkeypatch):
    app = _reload_app_without_env(monkeypatch)

    response = asyncio.run(_request(app, "GET", "/health"))

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_chat_without_api_key_returns_fallback(monkeypatch):
    app = _reload_app_without_env(monkeypatch)
    payload = {"messages": [{"role": "user", "content": "你好"}]}

    response = asyncio.run(_request(app, "POST", "/api/chat", json=payload))

    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["configured"] is False
    assert "你好" in data["reply"]


def test_provider_profiles_cover_mainstream_api_types():
    openai = Settings(_env_file=None, llm_provider="openai", openai_api_key="k").provider_profile()
    deepseek = Settings(_env_file=None, llm_provider="deepseek", deepseek_api_key="k").provider_profile()
    qwen = Settings(_env_file=None, llm_provider="qwen", qwen_api_key="k").provider_profile()
    anthropic = Settings(_env_file=None, llm_provider="anthropic", anthropic_auth_token="k").provider_profile()

    assert openai.api_type == "openai_compatible"
    assert deepseek.api_type == "openai_compatible"
    assert qwen.api_type == "openai_compatible"
    assert anthropic.api_type == "anthropic_compatible"


def test_strip_thinking_removes_reasoning_blocks():
    text = "<think>private chain</think>\n最终答案"

    assert strip_thinking(text) == "最终答案"


def test_provider_override_uses_requested_protocol(monkeypatch):
    monkeypatch.setenv("SPECTRUMCLAW_LLM_PROVIDER", "anthropic_compatible")
    monkeypatch.setenv("SPECTRUMCLAW_LLM_BASE_URL", "https://example.test")
    monkeypatch.setenv("SPECTRUMCLAW_LLM_API_KEY", "k")
    monkeypatch.setenv("SPECTRUMCLAW_LLM_MODEL", "m")
    get_settings.cache_clear()

    settings = get_settings()
    profile = settings.provider_profile(provider_override="openai_compatible")

    assert profile.api_type == "openai_compatible"


def test_openai_endpoint_accepts_domain_or_v1_base_url():
    assert _openai_endpoint("https://api.example.test") == "https://api.example.test/v1/chat/completions"
    assert _openai_endpoint("https://api.example.test/v1") == "https://api.example.test/v1/chat/completions"
