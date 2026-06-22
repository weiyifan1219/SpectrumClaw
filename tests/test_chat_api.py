from __future__ import annotations

import asyncio

import httpx

from backend.config import Settings, get_settings
from backend.llm.client import (
    _build_openai_payload,
    _execute_tools,
    _extract_text_tool_calls,
    _openai_reasoning_effort,
    _openai_thinking,
    _openai_endpoint,
    normalize_reasoning_effort,
    register_tool,
    strip_thinking,
)
from backend.llm.model_registry import llm_options_payload


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


def test_llm_options_expose_real_provider_model_and_reasoning(monkeypatch):
    for key in (
        "SPECTRUMCLAW_LLM_PROVIDER",
        "SPECTRUMCLAW_LLM_BASE_URL",
        "SPECTRUMCLAW_LLM_API_KEY",
        "SPECTRUMCLAW_LLM_MODEL",
        "SPECTRUMCLAW_DEEPSEEK_API_KEY",
        "SPECTRUMCLAW_DEEPSEEK_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir("/")
    monkeypatch.setenv("SPECTRUMCLAW_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("SPECTRUMCLAW_DEEPSEEK_API_KEY", "k")
    monkeypatch.setenv("SPECTRUMCLAW_DEEPSEEK_MODEL", "deepseek-v4-pro")
    get_settings.cache_clear()

    from backend.app import create_app

    app = create_app()
    response = asyncio.run(_request(app, "GET", "/api/llm/options"))

    assert response.status_code == 200
    data = response.json()
    active = data["active"]
    current = next(item for item in data["models"] if item["current"])
    deepseek_models = {item["model"]: item for item in data["models"] if item["provider"] == "deepseek"}

    assert active["provider"] == "deepseek"
    assert active["model"] == "deepseek-v4-pro"
    assert current["provider"] == "deepseek"
    assert current["model"] == "deepseek-v4-pro"
    assert current["configured"] is True
    assert current["supports_reasoning"] is True
    assert current["reasoning_efforts"] == ["off", "low", "medium", "high", "xhigh"]
    assert set(deepseek_models) == {"deepseek-v4-pro", "deepseek-v4-flash"}
    for option in deepseek_models.values():
        assert option["configured"] is True
        assert option["supports_reasoning"] is True
        assert option["reasoning_efforts"] == ["off", "low", "medium", "high", "xhigh"]
    assert [item["id"] for item in data["reasoning_options"]] == ["off", "low", "medium", "high", "xhigh"]


def test_reasoning_effort_max_alias_maps_to_xhigh():
    assert normalize_reasoning_effort("max") == "xhigh"


def test_llm_options_do_not_mark_deepseek_configured_from_generic_credentials():
    settings = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        llm_base_url="https://api.example.test/v1",
        llm_api_key="generic-key",
        llm_model="gpt-5-mini",
        deepseek_api_key="",
    )

    data = llm_options_payload(settings)
    deepseek_options = [item for item in data["models"] if item["model"].startswith("deepseek")]

    assert any(item["model"] == "gpt-5-mini" and item["configured"] for item in data["models"])
    assert deepseek_options
    assert all(item["configured"] is False for item in deepseek_options)


def test_llm_options_hide_anthropic_until_streaming_adapter_exists():
    settings = Settings(
        _env_file=None,
        llm_provider="openai",
        openai_api_key="openai-key",
        anthropic_auth_token="anthropic-key",
    )

    data = llm_options_payload(settings)

    assert all(item["provider"] != "anthropic" for item in data["models"])


def test_stream_endpoint_forwards_selected_provider_and_model(monkeypatch):
    seen = {}

    async def fake_stream_chat(*args, **kwargs):
        seen.update(kwargs)
        yield {"type": "done", "data": {"ok": True}}

    import backend.api.chat as chat_api

    monkeypatch.setattr(chat_api, "runtime_stream_chat", fake_stream_chat)

    from backend.app import create_app

    app = create_app()
    response = asyncio.run(
        _request(
            app,
            "POST",
            "/api/chat/stream",
            json={
                "messages": [{"role": "user", "content": "你好"}],
                "provider": "qwen",
                "model": "qwen-plus",
                "thinking_enabled": False,
                "reasoning_effort": None,
            },
        )
    )

    assert response.status_code == 200
    assert seen["provider_override"] == "qwen"
    assert seen["model_override"] == "qwen-plus"
    assert seen["thinking_enabled"] is False


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


def test_openai_payload_preserves_thinking_tool_history():
    tool_call = {
        "id": "call_test",
        "type": "function",
        "function": {"name": "get_time", "arguments": "{}"},
    }
    payload = _build_openai_payload(
        [
            {"role": "user", "content": "现在几点？"},
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "I should call the time tool.",
                "tool_calls": [tool_call],
            },
            {
                "role": "tool",
                "name": "get_time",
                "tool_call_id": "call_test",
                "content": "2026-05-29T00:00:00Z",
            },
        ],
        "deepseek-v4-pro",
        thinking={"type": "enabled"},
        reasoning_effort="xhigh",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_time",
                    "description": "获取当前时间",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    assistant_message = payload["messages"][2]
    tool_message = payload["messages"][3]

    assert assistant_message["reasoning_content"] == "I should call the time tool."
    assert assistant_message["tool_calls"] == [tool_call]
    assert tool_message["tool_call_id"] == "call_test"
    assert "name" not in tool_message
    assert "temperature" not in payload


def test_execute_tools_returns_matching_tool_name():
    register_tool(
        "unit_echo",
        lambda value="ok": {"value": value},
        {
            "name": "unit_echo",
            "description": "Echo a value",
            "parameters": {"type": "object", "properties": {"value": {"type": "string"}}},
        },
    )

    results = asyncio.run(
        _execute_tools([
            {
                "id": "call_echo",
                "type": "function",
                "function": {"name": "unit_echo", "arguments": '{"value": "ready"}'},
            }
        ])
    )

    assert results[0]["role"] == "tool"
    assert results[0]["tool_call_id"] == "call_echo"
    assert "ready" in results[0]["content"]


def test_extract_text_tool_call_from_xml_block():
    tools = [{
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Search KB",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    }]

    calls = _extract_text_tool_calls(
        """
        我需要查询知识库。
        <search_knowledge_base>
          <query>Region 3 frequency allocation</query>
        </search_knowledge_base>
        """,
        tools,
    )

    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "search_knowledge_base"
    assert calls[0]["function"]["arguments"] == '{"query": "Region 3 frequency allocation"}'


def test_reasoning_effort_accepts_off_and_four_strength_levels():
    assert normalize_reasoning_effort("off") is None
    assert normalize_reasoning_effort("low") == "low"
    assert normalize_reasoning_effort("medium") == "medium"
    assert normalize_reasoning_effort("high") == "high"
    assert normalize_reasoning_effort("xhigh") == "xhigh"
    assert normalize_reasoning_effort("max") == "xhigh"
    assert normalize_reasoning_effort("unknown") is None


def test_provider_specific_openai_compatible_reasoning_fields():
    deepseek = Settings(_env_file=None, llm_provider="deepseek", deepseek_api_key="k").provider_profile()
    qwen = Settings(_env_file=None, llm_provider="qwen", qwen_api_key="k").provider_profile()
    openai_reasoning = Settings(
        _env_file=None,
        llm_provider="openai",
        openai_api_key="k",
        openai_model="o3-mini",
    ).provider_profile()
    compatible_reasoning = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        llm_base_url="https://api.example.test/v1",
        llm_api_key="k",
        llm_model="gpt-5-mini",
    ).provider_profile()

    assert _openai_thinking(deepseek, True) == {"type": "enabled"}
    assert _openai_thinking(deepseek, False) == {"type": "disabled"}
    assert _openai_reasoning_effort(deepseek, "xhigh") == "xhigh"
    assert _openai_thinking(qwen, True) is None
    assert _openai_reasoning_effort(qwen, "xhigh") is None
    assert _openai_thinking(openai_reasoning, True) is None
    assert _openai_reasoning_effort(openai_reasoning, "medium") == "medium"
    assert _openai_reasoning_effort(openai_reasoning, "xhigh") == "high"
    assert _openai_reasoning_effort(compatible_reasoning, "xhigh") == "high"


def test_deepseek_tool_400_retries_with_thinking(monkeypatch):
    from backend.llm import client as llm_client

    sent_payloads = []

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            sent_payloads.append(json)
            request = httpx.Request("POST", url)
            if len(sent_payloads) == 1:
                return httpx.Response(400, text="thinking required", request=request)
            if len(sent_payloads) == 2:
                return httpx.Response(
                    200,
                    json={
                        "choices": [{
                            "message": {
                                "content": None,
                                "reasoning_content": "Need current time.",
                                "tool_calls": [{
                                    "id": "call_time",
                                    "type": "function",
                                    "function": {"name": "unit_time", "arguments": "{}"},
                                }],
                            }
                        }]
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "当前 UTC 时间为 2026-05-29T00:00:00Z。"}}]},
                request=request,
            )

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", FakeAsyncClient)
    register_tool(
        "unit_time",
        lambda: "2026-05-29T00:00:00Z",
        {
            "name": "unit_time",
            "description": "Get unit test time",
            "parameters": {"type": "object", "properties": {}},
        },
    )
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        deepseek_api_key="k",
        deepseek_model="deepseek-v4-pro",
    )

    reply, metadata = asyncio.run(
        llm_client.chat(
            [{"role": "user", "content": "现在是几点？"}],
            tool_names=["unit_time"],
            settings=settings,
        )
    )

    assert reply.startswith("当前 UTC 时间")
    assert metadata["auto_tool_thinking"] is True
    assert sent_payloads[0]["thinking"] == {"type": "disabled"}
    assert sent_payloads[1]["thinking"] == {"type": "enabled"}
    assert sent_payloads[1]["reasoning_effort"] == "high"
    assert sent_payloads[2]["messages"][2]["reasoning_content"] == "Need current time."
    assert sent_payloads[2]["messages"][3]["tool_call_id"] == "call_time"
    assert "name" not in sent_payloads[2]["messages"][3]


def test_tool_400_can_fallback_to_plain_chat(monkeypatch):
    from backend.llm import client as llm_client

    sent_payloads = []

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            sent_payloads.append(json)
            request = httpx.Request("POST", url)
            if len(sent_payloads) == 1:
                return httpx.Response(400, text="tools unsupported", request=request)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "普通对话降级成功。"}}]},
                request=request,
            )

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", FakeAsyncClient)
    settings = Settings(
        _env_file=None,
        llm_provider="qwen",
        qwen_api_key="k",
        qwen_model="qwen-plus",
    )

    reply, metadata = asyncio.run(
        llm_client.chat(
            [{"role": "user", "content": "你好"}],
            tool_names=["unit_time"],
            settings=settings,
        )
    )

    assert reply == "普通对话降级成功。"
    assert "tools" in sent_payloads[0]
    assert "tools" not in sent_payloads[1]
    assert metadata["tools_disabled_after_error"] is True


def test_stream_chat_executes_text_tool_call_before_final_stream(monkeypatch):
    from backend.llm import client as llm_client

    sent_posts = []
    sent_streams = []

    class FakeStreamResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"Region 3 检索完成。"}}]}'
            yield "data: [DONE]"

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            sent_posts.append(json)
            request = httpx.Request("POST", url)
            if len(sent_posts) == 1:
                return httpx.Response(
                    200,
                    json={
                        "choices": [{
                            "message": {
                                "content": (
                                    "<unit_kb_search>"
                                    "<query>Region 3 frequency allocation</query>"
                                    "</unit_kb_search>"
                                )
                            }
                        }]
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "工具结果已进入上下文。"}}]},
                request=request,
            )

        def stream(self, method, url, headers, json):
            sent_streams.append(json)
            return FakeStreamResponse()

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", FakeAsyncClient)
    register_tool(
        "unit_kb_search",
        lambda query: f"知识库结果: {query}",
        {
            "name": "unit_kb_search",
            "description": "Search unit test KB",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    )
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        deepseek_api_key="k",
        deepseek_model="deepseek-v4-pro",
    )

    async def collect():
        return [
            event
            async for event in llm_client.stream_chat(
                [{"role": "user", "content": "查一下 Region 3"}],
                tool_names=["unit_kb_search"],
                settings=settings,
            )
        ]

    events = asyncio.run(collect())

    assert sent_posts[1]["messages"][2]["tool_calls"][0]["function"]["name"] == "unit_kb_search"
    assert sent_posts[1]["messages"][3]["role"] == "tool"
    assert "知识库结果: Region 3 frequency allocation" in sent_posts[1]["messages"][3]["content"]
    assert sent_streams[0]["messages"][3]["role"] == "tool"
    assert events[0] == {"type": "thinking", "data": "已调用 1 次工具查询"}
    assert events[-2] == {"type": "content", "data": "Region 3 检索完成。"}
    assert events[-1]["data"]["tool_rounds"] == 1
