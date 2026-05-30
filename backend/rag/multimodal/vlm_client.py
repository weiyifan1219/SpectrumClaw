"""VLM client — Qwen-VL multimodal API for image/table/formula understanding."""

from __future__ import annotations

import base64
import os
from abc import ABC, abstractmethod
from pathlib import Path


class VLMClient(ABC):
    """Abstract VLM client for multimodal content understanding."""

    @abstractmethod
    async def describe_image(self, image_path: str, prompt: str) -> str: ...
    @abstractmethod
    async def describe_table(self, image_path: str, caption: str = "") -> str: ...
    @abstractmethod
    async def describe_equation(self, image_path: str, caption: str = "") -> str: ...
    @property
    @abstractmethod
    def configured(self) -> bool: ...


class QwenVLClient(VLMClient):
    """Qwen-VL via DashScope API (OpenAI-compatible).

    Env vars:
      QWEN_VL_API_KEY — required
      QWEN_VL_BASE_URL — default https://dashscope.aliyuncs.com/compatible-mode/v1
      QWEN_VL_MODEL — default qwen-vl-max
    """

    def __init__(self, api_key: str = "", base_url: str = "", model: str = "",
                 max_tokens: int = 1024):
        self.api_key = api_key or os.getenv("QWEN_VL_API_KEY", "")
        self.base_url = base_url or os.getenv(
            "QWEN_VL_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.model = model or os.getenv("QWEN_VL_MODEL", "qwen-vl-max")
        self.max_tokens = max_tokens
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def describe_image(self, image_path: str, prompt: str = "") -> str:
        default_prompt = (
            "You are analyzing a figure from an ITU-R spectrum management document. "
            "Describe this image in detail. Identify: "
            "1) What type of figure is this (spectrum allocation chart, block diagram, "
            "interference scenario, antenna pattern, etc.) "
            "2) Key frequency bands, services, and parameters visible "
            "3) Any relationships or constraints shown. "
            "Keep the description under 300 words."
        )
        return await self._call_vl(image_path, prompt or default_prompt)

    async def describe_table(self, image_path: str, caption: str = "") -> str:
        default_prompt = (
            "Convert this ITU-R spectrum table into a natural language description. "
            "For each row describe the frequency band, service, region, and constraints. "
            "Preserve all numerical values and units. "
            + (f"Caption: {caption}" if caption else "")
        )
        return await self._call_vl(image_path, default_prompt)

    async def describe_equation(self, image_path: str, caption: str = "") -> str:
        default_prompt = (
            "Extract this equation as LaTeX and explain each variable "
            "in the context of radio/wireless systems. "
            + (f"Caption: {caption}" if caption else "")
        )
        return await self._call_vl(image_path, default_prompt)

    async def _call_vl(self, image_path: str, prompt: str) -> str:
        if not self.configured:
            return f"[VLM not configured] {prompt[:100]}..."
        self._ensure_client()
        b64 = self._encode_image(image_path)
        ext = Path(image_path).suffix.lower().lstrip(".")
        mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}
        mime = mime_map.get(ext, "png")
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b64}"}},
                {"type": "text", "text": prompt},
            ]}],
            "max_tokens": self.max_tokens,
        }
        try:
            resp = self._client.chat.completions.create(**payload)
            return resp.choices[0].message.content
        except Exception as exc:
            return f"[VLM error: {exc}] {prompt[:100]}..."

    def _ensure_client(self):
        if self._client is not None:
            return
        from openai import OpenAI
        self._client = OpenAI(base_url=self.base_url, api_key=self.api_key)

    @staticmethod
    def _encode_image(path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
