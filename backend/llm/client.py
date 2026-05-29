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
    "你可以使用提供的工具（tools）来获取信息或执行操作，优先调用工具而不是凭空猜测。"
    "用户可以与你自由对话；回答问题时保持专业、准确，不知道就说不知道。"
    "当用户询问你的底层模型、版本或技术架构时，请如实、直接地回答，不需要遮掩或说「无法披露」。"
)

MAX_TOOL_ROUNDS = 5


def normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in messages:
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant", "system", "tool"}:
            continue
        entry: dict[str, Any] = {"role": role, "content": content}
        if role == "assistant" and "tool_calls" in item:
            entry["tool_calls"] = item["tool_calls"]
        if role == "tool" and "tool_call_id" in item:
            entry["tool_call_id"] = item["tool_call_id"]
        normalized.append(entry)
    return normalized[-40:]


def strip_thinking(text: str) -> str:
    return re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()


def fallback_reply(
    messages: list[dict[str, str]], provider: ProviderProfile
) -> tuple[str, dict[str, Any]]:
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
    """Normalize OpenAI-compatible chat completions URL."""
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _anthropic_endpoint(base_url: str) -> str:
    """Normalize Anthropic messages URL."""
    base = base_url.rstrip("/")
    if base.endswith("/messages"):
        return base
    return f"{base}/messages"


def _openai_headers(api_key: str) -> dict[str, str]:
    return {
        "content-type": "application/json",
        "authorization": f"Bearer {api_key}",
    }


def _anthropic_headers(api_key: str) -> dict[str, str]:
    return {
        "content-type": "application/json",
        "x-api-key": api_key,
    }


def _build_openai_payload(
    messages: list[dict[str, Any]],
    model: str,
    thinking: dict | None = None,
    reasoning_effort: str | None = None,
    tools: list[dict] | None = None,
) -> dict[str, Any]:
    payload_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # preserve tool_calls / tool_call_id in history
    for m in messages:
        entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
        if m["role"] == "assistant" and "tool_calls" in m:
            entry["tool_calls"] = m["tool_calls"]
        if m["role"] == "tool" and "tool_call_id" in m:
            entry["tool_call_id"] = m["tool_call_id"]
        payload_messages.append(entry)

    payload: dict[str, Any] = {
        "model": model,
        "messages": payload_messages,
        "max_tokens": 2048,
    }
    if thinking:
        payload["thinking"] = thinking
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    if tools:
        payload["tools"] = tools
    if not tools:
        payload["temperature"] = 0.7

    return payload


def _build_anthropic_payload(
    messages: list[dict[str, Any]],
    model: str,
    thinking_budget: int | None = None,
    reasoning_effort: str | None = None,
    tools: list[dict] | None = None,
) -> dict[str, Any]:
    system_parts = [SYSTEM_PROMPT]
    api_messages: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "system":
            system_parts.append(m["content"])
        elif m["role"] in ("user", "assistant"):
            entry: dict[str, Any] = {"role": m["role"], "content": m["content"]}
            if m["role"] == "assistant" and "tool_calls" in m:
                # convert OpenAI tool_calls → Anthropic tool_use blocks
                blocks = []
                for tc in m["tool_calls"]:
                    blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": json.loads(tc["function"]["arguments"]),
                    })
                entry["content"] = blocks
            api_messages.append(entry)
        elif m["role"] == "tool":
            api_messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id", ""),
                    "content": m["content"],
                }],
            })

    if not api_messages:
        api_messages = [{"role": "user", "content": "你好"}]

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": 2048,
        "system": "\n".join(system_parts),
        "messages": api_messages,
    }
    if thinking_budget:
        payload["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
    if reasoning_effort:
        payload.setdefault("output_config", {})["effort"] = reasoning_effort
    if tools:
        payload["tools"] = tools

    return payload


def _extract_openai_message(data: dict[str, Any]) -> dict[str, Any]:
    """Extract full message (content + tool_calls) from OpenAI-style response."""
    choices = data.get("choices") or []
    if not choices:
        return {"content": ""}
    msg = choices[0].get("message") or {}
    result: dict[str, Any] = {
        "content": strip_thinking(str(msg.get("content") or "")),
        "reasoning_content": msg.get("reasoning_content", ""),
    }
    if msg.get("tool_calls"):
        result["tool_calls"] = msg["tool_calls"]
    return result


def _extract_anthropic_text(data: dict[str, Any]) -> str:
    content = data.get("content", [])
    parts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif item.get("type") == "tool_use":
                    parts.append(f"[tool_call: {item.get('name', '')}]")
    text = "\n".join(parts) if parts else ""
    return strip_thinking(text)


# ── tool registry ──

TOOL_REGISTRY: dict[str, Any] = {}


def register_tool(name: str, fn: Any, schema: dict):
    TOOL_REGISTRY[name] = {"fn": fn, "schema": schema}


def get_tool_schemas(names: list[str] | None = None) -> list[dict]:
    """Return tool schemas in OpenAI format. If names is None, return all."""
    tools = []
    for name, entry in TOOL_REGISTRY.items():
        if names is None or name in names:
            tools.append({"type": "function", "function": entry["schema"]})
    return tools


def _build_anthropic_tools(schemas: list[dict]) -> list[dict]:
    """Convert OpenAI tool schemas to Anthropic format (name + input_schema)."""
    result = []
    for t in schemas:
        fn = t["function"]
        result.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return result


async def _execute_tools(tool_calls: list[dict]) -> list[dict]:
    """Execute tool calls and return tool result messages."""
    results = []
    for tc in tool_calls:
        fn_name = tc["function"]["name"]
        try:
            fn_args = json.loads(tc["function"]["arguments"])
        except (json.JSONDecodeError, KeyError):
            fn_args = {}
        entry = TOOL_REGISTRY.get(fn_name)
        if entry and callable(entry["fn"]):
            try:
                result = entry["fn"](**fn_args)
                content = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
            except Exception as exc:
                content = json.dumps({"error": str(exc)}, ensure_ascii=False)
        else:
            content = json.dumps({"error": f"Unknown tool: {fn_name}"}, ensure_ascii=False)
        results.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": content,
        })
    return results


# ── main chat function ──

async def chat(
    messages: list[dict[str, Any]],
    provider_override: str | None = None,
    model_override: str | None = None,
    thinking_enabled: bool = False,
    reasoning_effort: str | None = None,
    tool_names: list[str] | None = None,
    settings: Settings | None = None,
) -> tuple[str, dict[str, Any]]:
    active_settings = settings or get_settings()
    provider = active_settings.provider_profile(provider_override, model_override)
    normalized = normalize_messages(messages)

    if not provider.configured:
        return fallback_reply(normalized, provider)

    tool_schemas = get_tool_schemas(tool_names) if tool_names else None

    thinking = {"type": "enabled"} if thinking_enabled else None

    if provider.api_type == "openai_compatible":
        url = _openai_endpoint(provider.base_url)
        headers = _openai_headers(provider.api_key)
        payload = _build_openai_payload(
            normalized, provider.model,
            thinking=thinking,
            reasoning_effort=reasoning_effort if thinking_enabled else None,
            tools=tool_schemas,
        )
    elif provider.api_type == "anthropic_compatible":
        url = _anthropic_endpoint(provider.base_url)
        headers = _anthropic_headers(provider.api_key)
        anthropic_tools = _build_anthropic_tools(tool_schemas) if tool_schemas else None
        payload = _build_anthropic_payload(
            normalized, provider.model,
            thinking_budget=2048 if thinking_enabled else None,
            reasoning_effort=reasoning_effort if thinking_enabled else None,
            tools=anthropic_tools,
        )
    else:
        raise ValueError(f"Unsupported api_type: {provider.api_type}")

    tool_round = 0
    full_messages = list(normalized)
    all_reasoning: list[str] = []

    async with httpx.AsyncClient(timeout=provider.timeout) as client:
        while tool_round < MAX_TOOL_ROUNDS:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                preview = response.text[:160].replace("\n", " ")
                raise ValueError(f"LLM API returned non-JSON response: {preview}") from exc

            if provider.api_type == "openai_compatible":
                extracted = _extract_openai_message(data)
                reasoning = extracted.get("reasoning_content", "")
                if reasoning:
                    all_reasoning.append(reasoning)

                if extracted.get("tool_calls") and tool_schemas:
                    assistant_msg = {
                        "role": "assistant",
                        "content": extracted.get("content") or "",
                        "tool_calls": extracted["tool_calls"],
                    }
                    full_messages.append(assistant_msg)
                    tool_results = await _execute_tools(extracted["tool_calls"])
                    full_messages.extend(tool_results)
                    # rebuild payload with updated messages
                    payload = _build_openai_payload(
                        full_messages, provider.model,
                        thinking=thinking,
                        reasoning_effort=reasoning_effort if thinking_enabled else None,
                        tools=tool_schemas,
                    )
                    tool_round += 1
                    continue
                else:
                    reply = extracted["content"] or "模型返回为空。"
                    return reply, {
                        "configured": True,
                        "provider": provider.provider,
                        "api_type": provider.api_type,
                        "model": provider.model,
                        "thinking_enabled": thinking_enabled,
                        "reasoning_effort": reasoning_effort,
                        "reasoning": "\n\n".join(all_reasoning) if all_reasoning else "",
                        "tool_rounds": tool_round,
                    }

            elif provider.api_type == "anthropic_compatible":
                reply = _extract_anthropic_text(data) or "模型返回为空。"
                return reply, {
                    "configured": True,
                    "provider": provider.provider,
                    "api_type": provider.api_type,
                    "model": provider.model,
                    "thinking_enabled": thinking_enabled,
                    "reasoning_effort": reasoning_effort,
                    "tool_rounds": tool_round,
                }

        # exceeded max tool rounds
        return "工具调用轮次超限，请简化你的请求。", {
            "configured": True,
            "provider": provider.provider,
            "api_type": provider.api_type,
            "model": provider.model,
            "thinking_enabled": thinking_enabled,
            "reasoning_effort": reasoning_effort,
            "reasoning": "\n\n".join(all_reasoning) if all_reasoning else "",
            "tool_rounds": tool_round,
        }
