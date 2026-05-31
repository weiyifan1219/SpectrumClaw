from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ApiType = Literal["openai_compatible", "anthropic_compatible"]


class ProviderProfile(BaseModel):
    provider: str
    api_type: ApiType
    base_url: str
    api_key: str
    model: str
    timeout: float = 60.0

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


class Settings(BaseSettings):
    env: str = Field("local", validation_alias=AliasChoices("SPECTRUMCLAW_ENV"))
    agent_runtime: str = Field(
        "langgraph",
        validation_alias=AliasChoices("SPECTRUMCLAW_AGENT_RUNTIME"),
    )
    llm_provider: str = Field(
        "auto",
        validation_alias=AliasChoices("SPECTRUMCLAW_LLM_PROVIDER", "SPECTRUMCLAW_ACTIVE_PROVIDER", "ACTIVE_PROVIDER"),
    )
    llm_base_url: str = Field(
        "",
        validation_alias=AliasChoices("SPECTRUMCLAW_LLM_BASE_URL", "LLM_BASE_URL"),
    )
    llm_api_key: str = Field(
        "",
        validation_alias=AliasChoices("SPECTRUMCLAW_LLM_API_KEY", "LLM_API_KEY"),
    )
    llm_model: str = Field(
        "",
        validation_alias=AliasChoices("SPECTRUMCLAW_LLM_MODEL", "LLM_MODEL"),
    )
    llm_timeout: float = Field(60.0, validation_alias=AliasChoices("SPECTRUMCLAW_LLM_TIMEOUT", "LLM_TIMEOUT"))

    openai_base_url: str = Field(
        "https://api.openai.com/v1",
        validation_alias=AliasChoices("SPECTRUMCLAW_OPENAI_BASE_URL", "OPENAI_BASE_URL"),
    )
    openai_api_key: str = Field("", validation_alias=AliasChoices("SPECTRUMCLAW_OPENAI_API_KEY", "OPENAI_API_KEY"))
    openai_model: str = Field("gpt-4o", validation_alias=AliasChoices("SPECTRUMCLAW_OPENAI_MODEL", "OPENAI_MODEL"))

    deepseek_base_url: str = Field(
        "https://api.deepseek.com/v1",
        validation_alias=AliasChoices("SPECTRUMCLAW_DEEPSEEK_BASE_URL", "DEEPSEEK_BASE_URL"),
    )
    deepseek_api_key: str = Field(
        "",
        validation_alias=AliasChoices("SPECTRUMCLAW_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
    )
    deepseek_model: str = Field(
        "deepseek-v4-pro",
        validation_alias=AliasChoices("SPECTRUMCLAW_DEEPSEEK_MODEL", "DEEPSEEK_MODEL"),
    )
    deepseek_anthropic_base_url: str = Field(
        "https://api.deepseek.com/anthropic",
        validation_alias=AliasChoices("SPECTRUMCLAW_DEEPSEEK_ANTHROPIC_BASE_URL"),
    )

    qwen_base_url: str = Field(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias=AliasChoices("SPECTRUMCLAW_QWEN_BASE_URL", "QWEN_BASE_URL", "DASHSCOPE_BASE_URL"),
    )
    qwen_api_key: str = Field(
        "",
        validation_alias=AliasChoices("SPECTRUMCLAW_QWEN_API_KEY", "QWEN_API_KEY", "DASHSCOPE_API_KEY"),
    )
    qwen_model: str = Field("qwen-plus", validation_alias=AliasChoices("SPECTRUMCLAW_QWEN_MODEL", "QWEN_MODEL"))

    anthropic_base_url: str = Field(
        "https://api.anthropic.com",
        validation_alias=AliasChoices("SPECTRUMCLAW_ANTHROPIC_BASE_URL", "ANTHROPIC_BASE_URL"),
    )
    anthropic_auth_token: str = Field(
        "",
        validation_alias=AliasChoices("SPECTRUMCLAW_ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"),
    )
    anthropic_model: str = Field(
        "claude-3-5-sonnet-latest",
        validation_alias=AliasChoices("SPECTRUMCLAW_ANTHROPIC_MODEL", "ANTHROPIC_MODEL"),
    )

    # memory
    memory_enabled: bool = Field(
        True,
        validation_alias=AliasChoices("SPECTRUMCLAW_MEMORY_ENABLED"),
    )
    memory_db_path: str = Field(
        "data/memory/spectrum_memory.sqlite3",
        validation_alias=AliasChoices("SPECTRUMCLAW_MEMORY_DB_PATH"),
    )
    memory_inject_top_k: int = Field(
        5,
        validation_alias=AliasChoices("SPECTRUMCLAW_MEMORY_INJECT_TOP_K"),
    )
    memory_summarize_every_turns: int = Field(
        6,
        validation_alias=AliasChoices("SPECTRUMCLAW_MEMORY_SUMMARIZE_EVERY"),
    )

    # web search
    tavily_api_key: str = Field(
        "",
        validation_alias=AliasChoices("TAVILY_API_KEY"),
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    def provider_profile(
        self,
        provider_override: str | None = None,
        model_override: str | None = None,
    ) -> ProviderProfile:
        provider = (provider_override or self.llm_provider or "auto").strip()
        if provider == "auto":
            provider = self._auto_provider()

        profiles = {
            "openai": ProviderProfile(
                provider="openai",
                api_type="openai_compatible",
                base_url=self.llm_base_url or self.openai_base_url,
                api_key=self.llm_api_key or self.openai_api_key,
                model=model_override or self.llm_model or self.openai_model,
                timeout=self.llm_timeout,
            ),
            "deepseek": ProviderProfile(
                provider="deepseek",
                api_type="openai_compatible",
                base_url=self.llm_base_url or self.deepseek_base_url,
                api_key=self.llm_api_key or self.deepseek_api_key,
                model=model_override or self.llm_model or self.deepseek_model,
                timeout=self.llm_timeout,
            ),
            "qwen": ProviderProfile(
                provider="qwen",
                api_type="openai_compatible",
                base_url=self.llm_base_url or self.qwen_base_url,
                api_key=self.llm_api_key or self.qwen_api_key,
                model=model_override or self.llm_model or self.qwen_model,
                timeout=self.llm_timeout,
            ),
            "anthropic": ProviderProfile(
                provider="anthropic",
                api_type="anthropic_compatible",
                base_url=self.llm_base_url or self.anthropic_base_url,
                api_key=self.llm_api_key or self.anthropic_auth_token,
                model=model_override or self.llm_model or self.anthropic_model,
                timeout=self.llm_timeout,
            ),
            "openai_compatible": ProviderProfile(
                provider="openai_compatible",
                api_type="openai_compatible",
                base_url=self.llm_base_url,
                api_key=self.llm_api_key,
                model=model_override or self.llm_model,
                timeout=self.llm_timeout,
            ),
            "anthropic_compatible": ProviderProfile(
                provider="anthropic_compatible",
                api_type="anthropic_compatible",
                base_url=self.llm_base_url or self.anthropic_base_url,
                api_key=self.llm_api_key or self.anthropic_auth_token,
                model=model_override or self.llm_model or self.anthropic_model,
                timeout=self.llm_timeout,
            ),
        }
        if provider not in profiles:
            raise ValueError(f"Unsupported LLM provider: {provider}")
        return profiles[provider]

    def _auto_provider(self) -> str:
        if self.llm_base_url and self.llm_api_key and self.llm_model:
            lowered = self.llm_base_url.lower()
            if "anthropic" in lowered or "packyapi" in lowered:
                return "anthropic_compatible"
            return "openai_compatible"
        if self.deepseek_api_key:
            return "deepseek"
        if self.qwen_api_key:
            return "qwen"
        if self.openai_api_key:
            return "openai"
        if self.anthropic_auth_token:
            return "anthropic"
        return "openai_compatible"


@lru_cache
def get_settings() -> Settings:
    return Settings()
