from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..config import ProviderProfile, Settings


REASONING_EFFORT_IDS = ("low", "medium", "high", "xhigh")
REASONING_MODE_IDS = ("off", *REASONING_EFFORT_IDS)

REASONING_OPTIONS = [
    {"id": "off", "label": "Off", "description": "关闭推理"},
    {"id": "low", "label": "Low", "description": "更快响应"},
    {"id": "medium", "label": "Medium", "description": "均衡推理"},
    {"id": "high", "label": "High", "description": "更强推理"},
    {"id": "xhigh", "label": "XHigh", "description": "复杂任务"},
]

PROVIDER_LABELS = {
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "qwen": "Qwen",
    "anthropic": "Anthropic",
    "openai_compatible": "OpenAI-compatible",
    "anthropic_compatible": "Anthropic-compatible",
}

MODEL_LABELS = {
    "deepseek-v4-pro": "DeepSeek Pro",
    "deepseek-v4-flash": "DeepSeek Flash",
    "gpt-4o": "GPT-4o",
    "qwen-plus": "Qwen Plus",
    "claude-3-5-sonnet-latest": "Claude 3.5 Sonnet",
}

DEEPSEEK_MODELS = (
    "deepseek-v4-pro",
    "deepseek-v4-flash",
)


class ModelOption(BaseModel):
    id: str
    provider: str
    provider_label: str
    api_type: str
    model: str
    label: str
    configured: bool
    supports_reasoning: bool
    reasoning_efforts: list[str]
    current: bool


def reasoning_options() -> list[dict[str, str]]:
    return [dict(item) for item in REASONING_OPTIONS]


def supports_reasoning(profile: ProviderProfile) -> bool:
    if is_deepseek_profile(profile):
        return True

    return is_openai_reasoning_profile(profile)


def is_deepseek_profile(profile: ProviderProfile) -> bool:
    haystack = f"{profile.provider} {profile.base_url} {profile.model}".lower()
    return "deepseek" in haystack


def is_openai_reasoning_profile(profile: ProviderProfile) -> bool:
    if profile.api_type != "openai_compatible" or is_deepseek_profile(profile):
        return False
    model = profile.model.lower()
    return profile.provider in {"openai", "openai_compatible"} and model.startswith(("o1", "o3", "o4", "gpt-5"))


def is_stream_selectable(profile: ProviderProfile) -> bool:
    return profile.api_type == "openai_compatible"


def model_label(profile: ProviderProfile) -> str:
    return MODEL_LABELS.get(profile.model, profile.model or PROVIDER_LABELS.get(profile.provider, profile.provider))


def provider_label(profile: ProviderProfile) -> str:
    if profile.model.lower().startswith("deepseek"):
        return "DeepSeek"
    return PROVIDER_LABELS.get(profile.provider, profile.provider)


def same_credentials_with_model(profile: ProviderProfile, model: str) -> ProviderProfile:
    return ProviderProfile(
        provider=profile.provider,
        api_type=profile.api_type,
        base_url=profile.base_url,
        api_key=profile.api_key,
        model=model,
        timeout=profile.timeout,
    )


def provider_specific_profile(settings: Settings, provider: str) -> ProviderProfile:
    if provider == "deepseek":
        return ProviderProfile(
            provider="deepseek",
            api_type="openai_compatible",
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            timeout=settings.llm_timeout,
        )
    if provider == "openai":
        return ProviderProfile(
            provider="openai",
            api_type="openai_compatible",
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout=settings.llm_timeout,
        )
    if provider == "qwen":
        return ProviderProfile(
            provider="qwen",
            api_type="openai_compatible",
            base_url=settings.qwen_base_url,
            api_key=settings.qwen_api_key,
            model=settings.qwen_model,
            timeout=settings.llm_timeout,
        )
    if provider == "anthropic":
        return ProviderProfile(
            provider="anthropic",
            api_type="anthropic_compatible",
            base_url=settings.anthropic_base_url,
            api_key=settings.anthropic_auth_token,
            model=settings.anthropic_model,
            timeout=settings.llm_timeout,
        )
    raise ValueError(f"Unsupported provider-specific profile: {provider}")


def model_option(profile: ProviderProfile, active: ProviderProfile) -> ModelOption:
    can_reason = supports_reasoning(profile)
    return ModelOption(
        id=f"{profile.provider}:{profile.model}",
        provider=profile.provider,
        provider_label=provider_label(profile),
        api_type=profile.api_type,
        model=profile.model,
        label=model_label(profile),
        configured=profile.configured,
        supports_reasoning=can_reason,
        reasoning_efforts=list(REASONING_MODE_IDS) if can_reason else [],
        current=profile.provider == active.provider and profile.model == active.model,
    )


def llm_options_payload(settings: Settings) -> dict[str, Any]:
    active = settings.provider_profile()
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    active_is_deepseek = is_deepseek_profile(active)

    append_option(options, seen, active, active)

    for provider in ("openai", "qwen"):
        profile = provider_specific_profile(settings, provider)
        if not profile.configured:
            continue
        if active_is_deepseek:
            continue
        append_option(options, seen, profile, active)

    deepseek_template = active if active.configured and active_is_deepseek else provider_specific_profile(settings, "deepseek")
    for model in DEEPSEEK_MODELS:
        append_option(options, seen, same_credentials_with_model(deepseek_template, model), active)

    if settings.llm_base_url and settings.llm_model:
        compatible_provider = (
            settings.llm_provider
            if settings.llm_provider in {"openai_compatible", "anthropic_compatible"}
            else active.provider
        )
        profile = settings.provider_profile(provider_override=compatible_provider, model_override=settings.llm_model)
        append_option(options, seen, profile, active)

    return {
        "active": {
            "provider": active.provider,
            "api_type": active.api_type,
            "model": active.model,
            "configured": active.configured,
        },
        "models": options,
        "reasoning_options": reasoning_options(),
    }


def append_option(
    options: list[dict[str, Any]],
    seen: set[str],
    profile: ProviderProfile,
    active: ProviderProfile,
) -> None:
    if not profile.model or not is_stream_selectable(profile):
        return
    key = f"{profile.provider}:{profile.model}"
    if key in seen:
        return
    seen.add(key)
    options.append(model_option(profile, active).model_dump())
