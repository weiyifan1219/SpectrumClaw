from __future__ import annotations

import asyncio
import re
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..config import ProviderProfile, Settings, get_settings

# Skills with these implementation files are considered "implemented", not just
# scaffolded. README-only skills are scaffolds and shown as planned.
_SKILL_IMPL_MARKERS = (
    "planner.py", "agent.py", "generator.py",
    "genspectra_runner.py", "service.py", "pipeline.py",
)

# Skill metadata (display name + Chinese label) — keys must match directory names
# under backend/skills/.
_SKILL_META: dict[str, dict[str, str]] = {
    "frequency_planning":     {"cn": "频率规划",   "desc": "ITU-R 文档 RAG，输出频段划分、共存约束和带引用规划建议"},
    "spectrum_construction":  {"cn": "频谱构建",   "desc": "Gudmundson 物理模型生成多分辨率频谱图，可选 GenSpectra 重建"},
    "spectrum_decision":      {"cn": "频谱决策",   "desc": "CQI-Shannon 速率模型 + SLSQP 比例公平优化进行多用户资源分配"},
    "situation_building":     {"cn": "态势构建",   "desc": "频谱态势感知与可视化"},
    "interference_analysis":  {"cn": "干扰分析",   "desc": "互调/杂散/邻频干扰评估"},
    "modulation_recognition": {"cn": "调制识别",   "desc": "调制方式特征提取与分类"},
}

# Static description of always-on tools — kept short; the actual tool list also
# arrives in the messages payload via `tools=`.
_TOOLS_HINT = (
    "你可以使用以下工具：search_knowledge_base（ITU 知识库检索）、web_search（互联网搜索）、"
    "web_fetch（抓取网页）、get_weather、get_time、get_system_status。"
    "遇到需要实时数据、最新信息或知识截止日期之后的事件时，主动调用工具而不是凭空猜测。"
)

_BASE_PROMPT = (
    "你是 SpectrumClaw，一个电磁频谱领域的 AI 智能体。"
    "你的职责是：频率规划、频谱构建、频谱决策、干扰分析、调制识别等频谱相关任务。"
)

_OUTPUT_RULES = (
    "用户可以与你自由对话；回答问题时保持专业、准确。"
    "当用户询问你的底层模型、版本或技术架构时，请如实直接回答。"
    "回答专业问题时，优先使用 search_knowledge_base 从本地 ITU 知识库检索；"
    "如果知识库没有相关内容，再用 web_search 搜索互联网。"
    "引用知识库内容时标注文档编号（如 📄 R-REC-M.xxx），引用网页时标注来源 URL。"
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SKILLS_DIR = _PROJECT_ROOT / "backend" / "skills"

_PROMPT_CACHE: dict[str, Any] = {"text": None, "expires_at": 0.0}
_PROMPT_TTL_SEC = 300.0  # rebuild at most once every 5 minutes


def _scan_skills() -> tuple[list[tuple[str, dict[str, str]]], list[tuple[str, dict[str, str]]]]:
    """Scan backend/skills/ and split into (implemented, planned).

    Implemented = directory contains a real implementation file (not just README).
    """
    implemented: list[tuple[str, dict[str, str]]] = []
    planned: list[tuple[str, dict[str, str]]] = []
    if not _SKILLS_DIR.exists():
        return implemented, planned
    for entry in sorted(_SKILLS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_") or entry.name == "__pycache__":
            continue
        meta = _SKILL_META.get(entry.name, {"cn": entry.name, "desc": ""})
        has_impl = any((entry / m).exists() for m in _SKILL_IMPL_MARKERS)
        (implemented if has_impl else planned).append((entry.name, meta))
    return implemented, planned


def _latest_evolution_summary() -> str | None:
    """Best-effort: read latest evolution report summary from the memory store."""
    try:
        from ..memory.service import get_memory_service
        svc = get_memory_service()
        reports = svc.list_reports(limit=1)
        if reports:
            r = reports[0]
            summary = getattr(r, "summary", None) or (r.get("summary") if isinstance(r, dict) else None)
            if summary:
                return str(summary)[:300]
    except Exception:
        pass
    return None


def _build_system_prompt() -> str:
    """Assemble system prompt from current skill registry + memory state.

    The prompt rebuilds at most once every _PROMPT_TTL_SEC so a hot path doesn't
    re-scan the filesystem on every chat call.
    """
    now = time.time()
    if _PROMPT_CACHE["text"] is not None and now < _PROMPT_CACHE["expires_at"]:
        return _PROMPT_CACHE["text"]

    implemented, planned = _scan_skills()
    parts = [_BASE_PROMPT]

    if implemented:
        impl_lines = "、".join(f"{m['cn']}（{name}）" for name, m in implemented)
        parts.append(
            f"当前已实现的 skill 链路：{impl_lines}。这些 skill 已在系统中可用——"
            "如果用户的需求匹配某个 skill，可以建议用户在控制台选择对应技能卡运行；"
            "你也可以直接调用 search_knowledge_base 等工具配合回答。"
        )
    if planned:
        plan_lines = "、".join(f"{m['cn']}（{name}）" for name, m in planned)
        parts.append(
            f"以下 skill 仍在规划中（仅有占位、暂未实现）：{plan_lines}。"
            "不要声称这些 skill 已完成实际执行。"
        )

    parts.append(_TOOLS_HINT)

    evo = _latest_evolution_summary()
    if evo:
        parts.append(f"系统最近一次自我反思摘要（来自记忆与进化模块）：{evo}")

    parts.append(_OUTPUT_RULES)
    text = " ".join(parts)
    _PROMPT_CACHE["text"] = text
    _PROMPT_CACHE["expires_at"] = now + _PROMPT_TTL_SEC
    return text


def reset_system_prompt_cache() -> None:
    """Force the next chat call to rebuild the system prompt."""
    _PROMPT_CACHE["text"] = None
    _PROMPT_CACHE["expires_at"] = 0.0


MAX_TOOL_ROUNDS = 5
REASONING_EFFORTS = {"low", "high", "xhigh", "max"}


def normalize_reasoning_effort(effort: str | None) -> str | None:
    if not effort:
        return None
    normalized = str(effort).strip().lower().replace("_", "-")
    aliases = {
        "x-high": "xhigh",
        "extra-high": "xhigh",
        "extra-highest": "xhigh",
        "maximum": "max",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in REASONING_EFFORTS else None


def _is_deepseek_profile(provider: ProviderProfile) -> bool:
    haystack = f"{provider.provider} {provider.base_url} {provider.model}".lower()
    return "deepseek" in haystack


def _is_openai_reasoning_profile(provider: ProviderProfile) -> bool:
    model = provider.model.lower()
    return provider.provider == "openai" and model.startswith(("o1", "o3", "o4", "gpt-5"))


def _openai_reasoning_effort(provider: ProviderProfile, effort: str | None) -> str | None:
    if not effort:
        return None
    if _is_deepseek_profile(provider):
        return effort
    if _is_openai_reasoning_profile(provider):
        return "high" if effort in {"xhigh", "max"} else effort
    return None


def _openai_thinking(provider: ProviderProfile, thinking_enabled: bool) -> dict | None:
    if thinking_enabled and _is_deepseek_profile(provider):
        return {"type": "enabled"}
    return None


def _anthropic_thinking_budget(effort: str | None) -> int:
    budgets = {
        "low": 1024,
        "high": 2048,
        "xhigh": 4096,
        "max": 8192,
    }
    return budgets.get(effort or "high", 2048)


def normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in messages:
        role = str(item.get("role", "")).strip()
        content = item.get("content", "")
        if content is None:
            content = ""
        content = str(content).strip()
        if role not in {"user", "assistant", "system", "tool"}:
            continue
        entry: dict[str, Any] = {"role": role, "content": content}
        if role == "assistant":
            if "tool_calls" in item:
                entry["tool_calls"] = item["tool_calls"]
            if item.get("reasoning_content") is not None:
                entry["reasoning_content"] = str(item.get("reasoning_content", ""))
        if role == "tool":
            if "tool_call_id" in item:
                entry["tool_call_id"] = item["tool_call_id"]
            if item.get("name"):
                entry["name"] = str(item["name"])
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
    if urlsplit(base).path.rstrip("/"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


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
        "anthropic-version": "2023-06-01",
    }


def _build_openai_payload(
    messages: list[dict[str, Any]],
    model: str,
    thinking: dict | None = None,
    reasoning_effort: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 8192,
) -> dict[str, Any]:
    payload_messages = [{"role": "system", "content": _build_system_prompt()}]
    # preserve tool_calls / tool_call_id in history
    for m in messages:
        entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
        if m["role"] == "assistant":
            if "tool_calls" in m:
                entry["tool_calls"] = m["tool_calls"]
            if m.get("reasoning_content") is not None:
                entry["reasoning_content"] = m["reasoning_content"]
        if m["role"] == "tool":
            if "tool_call_id" in m:
                entry["tool_call_id"] = m["tool_call_id"]
        payload_messages.append(entry)

    payload: dict[str, Any] = {
        "model": model,
        "messages": payload_messages,
        "max_tokens": max_tokens,
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
    system_parts = [_build_system_prompt()]
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
    }
    if msg.get("reasoning_content") is not None:
        result["reasoning_content"] = msg.get("reasoning_content", "")
    if msg.get("tool_calls"):
        result["tool_calls"] = msg["tool_calls"]
    return result


def _extract_anthropic_message(data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", [])
    parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif item.get("type") == "tool_use":
                    tool_calls.append({
                        "id": item.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": item.get("name", ""),
                            "arguments": json.dumps(item.get("input") or {}, ensure_ascii=False),
                        },
                    })
    text = "\n".join(parts) if parts else ""
    result: dict[str, Any] = {"content": strip_thinking(text)}
    if tool_calls:
        result["tool_calls"] = tool_calls
    return result


def _extract_anthropic_text(data: dict[str, Any]) -> str:
    return _extract_anthropic_message(data).get("content", "")


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


def _coerce_text_tool_arg(value: str, schema: dict[str, Any]) -> Any:
    value = value.strip()
    arg_type = schema.get("type")
    if arg_type == "integer":
        try:
            return int(value)
        except ValueError:
            return value
    if arg_type == "number":
        try:
            return float(value)
        except ValueError:
            return value
    if arg_type == "boolean":
        return value.lower() in {"1", "true", "yes", "y", "是"}
    return value


def _extract_text_tool_calls(content: str, tools: list[dict] | None) -> list[dict]:
    """Parse XML-like tool tags emitted as text into OpenAI-style tool calls.

    Some OpenAI-compatible models occasionally render a tool request as:
      <search_knowledge_base><query>Region 3</query></search_knowledge_base>
    instead of returning a structured tool_calls field. Treat that as a
    recoverable tool call only when the tool was explicitly allowed.
    """
    if not content or not tools:
        return []

    tool_by_name = {
        str(t.get("function", {}).get("name", "")): t.get("function", {})
        for t in tools
        if t.get("function", {}).get("name")
    }
    calls: list[dict] = []

    for tool_name, fn_schema in tool_by_name.items():
        pattern = rf"<{re.escape(tool_name)}\b[^>]*>(?P<body>[\s\S]*?)</{re.escape(tool_name)}>"
        for match in re.finditer(pattern, content, flags=re.IGNORECASE):
            body = match.group("body").strip()
            args: dict[str, Any] = {}

            if body.startswith("{"):
                try:
                    parsed = json.loads(body)
                    if isinstance(parsed, dict):
                        args = parsed
                except json.JSONDecodeError:
                    args = {}

            properties = fn_schema.get("parameters", {}).get("properties", {})
            if not args:
                for arg_name, arg_schema in properties.items():
                    arg_pattern = rf"<{re.escape(arg_name)}\b[^>]*>(?P<value>[\s\S]*?)</{re.escape(arg_name)}>"
                    arg_match = re.search(arg_pattern, body, flags=re.IGNORECASE)
                    if arg_match:
                        args[arg_name] = _coerce_text_tool_arg(arg_match.group("value"), arg_schema)

            if not args and properties:
                required = fn_schema.get("parameters", {}).get("required", [])
                default_arg = required[0] if required else next(iter(properties))
                stripped_body = re.sub(r"<[^>]+>", " ", body)
                stripped_body = re.sub(r"\s+", " ", stripped_body).strip()
                if stripped_body:
                    args[default_arg] = _coerce_text_tool_arg(stripped_body, properties.get(default_arg, {}))

            if args:
                calls.append({
                    "id": f"call_text_{len(calls) + 1}_{tool_name}",
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(args, ensure_ascii=False),
                    },
                })

    return calls


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
                fn = entry["fn"]
                if asyncio.iscoroutinefunction(fn):
                    result = await fn(**fn_args)
                else:
                    result = fn(**fn_args)
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
    normalized_reasoning_effort = normalize_reasoning_effort(reasoning_effort)

    thinking = None
    payload_reasoning_effort = None

    if provider.api_type == "openai_compatible":
        thinking = _openai_thinking(provider, thinking_enabled)
        payload_reasoning_effort = _openai_reasoning_effort(
            provider,
            normalized_reasoning_effort if thinking_enabled else None,
        )
        url = _openai_endpoint(provider.base_url)
        headers = _openai_headers(provider.api_key)
        payload = _build_openai_payload(
            normalized, provider.model,
            thinking=thinking,
            reasoning_effort=payload_reasoning_effort,
            tools=tool_schemas,
        )
    elif provider.api_type == "anthropic_compatible":
        url = _anthropic_endpoint(provider.base_url)
        headers = _anthropic_headers(provider.api_key)
        anthropic_tools = _build_anthropic_tools(tool_schemas) if tool_schemas else None
        payload = _build_anthropic_payload(
            normalized, provider.model,
            thinking_budget=_anthropic_thinking_budget(normalized_reasoning_effort) if thinking_enabled else None,
            tools=anthropic_tools,
        )
    else:
        raise ValueError(f"Unsupported api_type: {provider.api_type}")

    tool_round = 0
    full_messages = list(normalized)
    all_reasoning: list[str] = []
    auto_tool_thinking = False
    tools_disabled_after_error = False

    async with httpx.AsyncClient(timeout=provider.timeout) as client:
        while tool_round < MAX_TOOL_ROUNDS:
            response = await client.post(url, headers=headers, json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                can_retry_deepseek_tool = (
                    exc.response.status_code == 400
                    and provider.api_type == "openai_compatible"
                    and _is_deepseek_profile(provider)
                    and bool(tool_schemas)
                    and not thinking_enabled
                    and not auto_tool_thinking
                )
                if can_retry_deepseek_tool:
                    auto_tool_thinking = True
                    thinking = {"type": "enabled"}
                    payload_reasoning_effort = normalized_reasoning_effort or "high"
                    payload = _build_openai_payload(
                        full_messages,
                        provider.model,
                        thinking=thinking,
                        reasoning_effort=payload_reasoning_effort,
                        tools=tool_schemas,
                    )
                    continue
                can_retry_without_tools = (
                    exc.response.status_code == 400
                    and bool(tool_schemas)
                    and not tools_disabled_after_error
                )
                if can_retry_without_tools:
                    tools_disabled_after_error = True
                    if provider.api_type == "openai_compatible":
                        payload = _build_openai_payload(
                            full_messages,
                            provider.model,
                            thinking=thinking,
                            reasoning_effort=payload_reasoning_effort,
                            tools=None,
                        )
                    else:
                        payload = _build_anthropic_payload(
                            full_messages,
                            provider.model,
                            thinking_budget=_anthropic_thinking_budget(normalized_reasoning_effort) if thinking_enabled else None,
                            tools=None,
                        )
                    continue
                raise
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
                text_tool_calls = _extract_text_tool_calls(extracted.get("content", ""), tool_schemas)
                tool_calls = extracted.get("tool_calls") or text_tool_calls

                if tool_calls and tool_schemas:
                    assistant_msg = {
                        "role": "assistant",
                        "content": "" if text_tool_calls and not extracted.get("tool_calls") else extracted.get("content") or "",
                        "tool_calls": tool_calls,
                    }
                    if extracted.get("reasoning_content") is not None:
                        assistant_msg["reasoning_content"] = extracted.get("reasoning_content", "")
                    full_messages.append(assistant_msg)
                    tool_results = await _execute_tools(tool_calls)
                    full_messages.extend(tool_results)
                    # if any tool returned an error, break loop and let model respond
                    any_error = any(
                        r.get("content", "").startswith('{"error"') or '"error":' in r.get("content", "")
                        for r in tool_results
                    )
                    if any_error and tool_round >= 1:
                        break
                    # rebuild payload with updated messages
                    payload = _build_openai_payload(
                        full_messages, provider.model,
                        thinking=thinking,
                        reasoning_effort=payload_reasoning_effort,
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
                        "reasoning_effort": normalized_reasoning_effort,
                        "auto_tool_thinking": auto_tool_thinking,
                        "tools_disabled_after_error": tools_disabled_after_error,
                        "reasoning": "\n\n".join(all_reasoning) if all_reasoning else "",
                        "tool_rounds": tool_round,
                    }

            elif provider.api_type == "anthropic_compatible":
                extracted = _extract_anthropic_message(data)
                text_tool_calls = _extract_text_tool_calls(extracted.get("content", ""), tool_schemas)
                tool_calls = extracted.get("tool_calls") or text_tool_calls
                if tool_calls and tool_schemas:
                    full_messages.append({
                        "role": "assistant",
                        "content": "" if text_tool_calls and not extracted.get("tool_calls") else extracted.get("content") or "",
                        "tool_calls": tool_calls,
                    })
                    tool_results = await _execute_tools(tool_calls)
                    full_messages.extend(tool_results)
                    payload = _build_anthropic_payload(
                        full_messages,
                        provider.model,
                        thinking_budget=_anthropic_thinking_budget(normalized_reasoning_effort) if thinking_enabled else None,
                        tools=anthropic_tools,
                    )
                    tool_round += 1
                    continue
                else:
                    reply = extracted.get("content") or "模型返回为空。"
                    return reply, {
                        "configured": True,
                        "provider": provider.provider,
                        "api_type": provider.api_type,
                        "model": provider.model,
                        "thinking_enabled": thinking_enabled,
                        "reasoning_effort": normalized_reasoning_effort,
                        "tools_disabled_after_error": tools_disabled_after_error,
                        "tool_rounds": tool_round,
                    }

        # exceeded max tool rounds — make one final call without tools
        try:
            final_payload = _build_openai_payload(
                full_messages, provider.model,
                thinking=thinking,
                reasoning_effort=payload_reasoning_effort,
                tools=None,
            )
            final_resp = await client.post(url, headers=headers, json=final_payload)
            final_resp.raise_for_status()
            final_data = final_resp.json()
            final_msg = _extract_openai_message(final_data)
            reply = final_msg.get("content") or "模型返回为空。"
            return reply, {
                "configured": True,
                "provider": provider.provider,
                "api_type": provider.api_type,
                "model": provider.model,
                "thinking_enabled": thinking_enabled,
                "reasoning_effort": normalized_reasoning_effort,
                "auto_tool_thinking": auto_tool_thinking,
                "tools_disabled_after_error": tools_disabled_after_error,
                "reasoning": "\n\n".join(all_reasoning) if all_reasoning else "",
                "tool_rounds": tool_round,
            }
        except Exception:
            return "工具调用轮次超限，请简化你的请求。", {
            "configured": True,
            "provider": provider.provider,
            "api_type": provider.api_type,
            "model": provider.model,
            "thinking_enabled": thinking_enabled,
            "reasoning_effort": normalized_reasoning_effort,
            "auto_tool_thinking": auto_tool_thinking,
            "tools_disabled_after_error": tools_disabled_after_error,
            "reasoning": "\n\n".join(all_reasoning) if all_reasoning else "",
            "tool_rounds": tool_round,
        }


# ── streaming chat ──

async def stream_chat(
    messages: list[dict[str, Any]],
    provider_override: str | None = None,
    model_override: str | None = None,
    thinking_enabled: bool = False,
    reasoning_effort: str | None = None,
    tool_names: list[str] | None = None,
    settings: Settings | None = None,
):
    """Streaming chat with tool calling. Tool execution is non-streaming.
    Yields: {"type":"thinking","data":...} | {"type":"content","data":...} | {"type":"done","data":...}"""
    active_settings = settings or get_settings()
    provider = active_settings.provider_profile(provider_override, model_override)
    normalized = normalize_messages(messages)

    if not provider.configured:
        text, meta = fallback_reply(normalized, provider)
        yield {"type": "content", "data": text}
        yield {"type": "done", "data": meta}
        return

    tool_schemas = get_tool_schemas(tool_names) if tool_names else None
    nre = normalize_reasoning_effort(reasoning_effort)

    thinking = None; pr_effort = None
    if provider.api_type == "openai_compatible":
        thinking = _openai_thinking(provider, thinking_enabled)
        pr_effort = _openai_reasoning_effort(provider, nre if thinking_enabled else None)
        url = _openai_endpoint(provider.base_url)
        headers = _openai_headers(provider.api_key)
    else:
        url = _anthropic_endpoint(provider.base_url)
        headers = _anthropic_headers(provider.api_key)

    tool_round = 0
    full_messages = list(normalized)

    async with httpx.AsyncClient(timeout=provider.timeout * 2) as client:
        # ── hidden tool loop ──
        while tool_round < MAX_TOOL_ROUNDS and tool_schemas:
            payload = _build_openai_payload(full_messages, provider.model, thinking=thinking,
                                              reasoning_effort=pr_effort, tools=tool_schemas)
            r = await client.post(url, headers=headers, json=payload)
            try: r.raise_for_status()
            except httpx.HTTPStatusError: break

            extracted = _extract_openai_message(r.json())
            text_tool_calls = _extract_text_tool_calls(extracted.get("content", ""), tool_schemas)
            tool_calls = extracted.get("tool_calls") or text_tool_calls
            if tool_calls:
                full_messages.append({
                    "role": "assistant",
                    "content": "" if text_tool_calls and not extracted.get("tool_calls") else extracted.get("content", ""),
                    "tool_calls": tool_calls,
                })
                tr = await _execute_tools(tool_calls)
                full_messages.extend(tr)
                tool_round += 1
                continue
            break

        if tool_round > 0:
            yield {"type": "thinking", "data": f"已调用 {tool_round} 次工具查询"}

        # ── stream final response ──
        sp = _build_openai_payload(full_messages, provider.model, thinking=thinking,
                                    reasoning_effort=pr_effort, tools=None)
        sp["stream"] = True

        async with client.stream("POST", url, headers=headers, json=sp) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "): continue
                ds = line[6:]
                if ds == "[DONE]": break
                try: chunk = json.loads(ds)
                except json.JSONDecodeError: continue
                delta = (chunk.get("choices",[{}])[0] or {}).get("delta", {})
                if delta.get("reasoning_content"):
                    yield {"type": "thinking", "data": delta["reasoning_content"]}
                if delta.get("content"):
                    yield {"type": "content", "data": delta["content"]}

        yield {"type": "done", "data": {"configured":True,"provider":provider.provider,
                "api_type":provider.api_type,"model":provider.model,"tool_rounds":tool_round}}
