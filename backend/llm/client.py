from __future__ import annotations

import re
import json
from typing import Any

import httpx

from ..config import ProviderProfile, Settings, get_settings


SYSTEM_PROMPT = (
    "你是 SpectrumClaw，一个电磁频谱领域的 AI 智能体。"
    "你的职责是：频率规划、态势构建、资源分配、干扰分析、调制识别等频谱相关任务。"
    "当前 skill 链路（频率规划/态势构建/资源分配）已规划但尚未全部实现，"
    "除非用户明确选中了对应技能卡并在上下文中可见，不要声称已完成了这些 skill 的实际执行。"
    "用户可以与你自由对话；回答问题时保持专业、准确，不知道就说不知道。"
    "当用户询问你的底层模型、版本或技术架构时，请如实、直接地回答，不需要遮掩或说「无法披露」。"
)


def normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in messages:
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant", "system"} or not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized[-20:]


def strip_thinking(text: str) -> str:
    return re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()


def fallback_reply(messages: list[dict[str, str]], provider: ProviderProfile) -> tuple[str, dict[str, Any]]:
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    reply = "已收到你的消息。当前后端未检测到完整的大模型 API 配置，因此返回本地确定性回复。"
    if last_user:
        reply += f" 你的最新输入是：{last_user}"
    return reply, {
        "configured": False,
        "provider": provider.provider,
        "api_type": provider.api_type,
        "model": provider.model,
    }


def _endpoint(base_url: str, suffix: str) -> str:
    base = base_url.rstrip("/")
    suffix = suffix.strip("/")
    if base.endswith(f"/{suffix}"):
        return base
    return f"{base}/{suffix}"


def _openai_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _openai_payload(messages: list[dict[str, str]], model: str) -> dict[str, Any]:
    payload_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    payload_messages.extend(messages)
    return {
        "model": model,
        "messages": payload_messages,
        "temperature": 0.7,
        "max_tokens": 1024,
    }


def _extract_openai_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return strip_thinking(str(message.get("content") or ""))


def _anthropic_payload(messages: list[dict[str, str]], model: str) -> dict[str, Any]:
    system_parts = [SYSTEM_PROMPT]
    api_messages: list[dict[str, str]] = []
    for message in messages:
        if message["role"] == "system":
            system_parts.append(message["content"])
        else:
            api_messages.append(message)
    if not api_messages:
        api_messages = [{"role": "user", "content": "你好"}]
    return {
        "model": model,
        "max_tokens": 1024,
        "system": "\n".join(system_parts),
        "messages": api_messages,
    }


def _extract_anthropic_text(data: dict[str, Any]) -> str:
    content = data.get("content", [])
    parts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
    if parts:
        return strip_thinking("\n".join(part for part in parts if part))
    return strip_thinking(str(data.get("text") or data.get("message") or ""))


async def chat(
    messages: list[dict[str, Any]],
    provider_override: str | None = None,
    model_override: str | None = None,
    settings: Settings | None = None,
) -> tuple[str, dict[str, Any]]:
    active_settings = settings or get_settings()
    provider = active_settings.provider_profile(provider_override, model_override)
    normalized = normalize_messages(messages)

    if not provider.configured:
        return fallback_reply(normalized, provider)

    if provider.api_type == "openai_compatible":
        url = _openai_endpoint(provider.base_url)
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {provider.api_key}",
        }
        payload = _openai_payload(normalized, provider.model)
        extractor = _extract_openai_text
    elif provider.api_type == "anthropic_compatible":
        url = _endpoint(provider.base_url, "v1/messages")
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": provider.api_key,
        }
        payload = _anthropic_payload(normalized, provider.model)
        extractor = _extract_anthropic_text
    else:
        raise ValueError(f"Unsupported api_type: {provider.api_type}")

    async with httpx.AsyncClient(timeout=provider.timeout) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            preview = response.text[:160].replace("\n", " ")
            raise ValueError(f"LLM API returned non-JSON response: {preview}") from exc

    reply = extractor(data) or "模型返回为空。"
    return reply, {
        "configured": True,
        "provider": provider.provider,
        "api_type": provider.api_type,
        "model": provider.model,
    }
