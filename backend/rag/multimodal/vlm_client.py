"""VLM client — Qwen-VL multimodal API or local model for image/table/formula understanding."""

from __future__ import annotations

import asyncio
import base64
import json
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

    async def describe_image(self, image_path: str, prompt: str = "",
                              captions: str = "", footnotes: str = "",
                              context: str = "", entity_name: str = "") -> str:
        from ..prompts import PROMPTS
        p = prompt or PROMPTS["image_analysis"].format(
            entity_name=entity_name or Path(image_path).stem,
            captions=captions or "none",
            footnotes=footnotes or "none",
            context=context or "none",
        )
        return await self._call_vl(image_path, p)

    async def describe_table(self, image_path: str, caption: str = "",
                              table_body: str = "", table_footnote: str = "",
                              context: str = "", entity_name: str = "") -> str:
        from ..prompts import PROMPTS
        p = PROMPTS["table_analysis"].format(
            entity_name=entity_name or Path(image_path).stem,
            table_caption=caption or "none",
            table_body=table_body or "none",
            table_footnote=table_footnote or "none",
            context=context or "none",
        )
        return await self._call_vl(image_path, p)

    async def describe_equation(self, image_path: str, caption: str = "",
                                 equation_text: str = "", equation_format: str = "latex",
                                 context: str = "", entity_name: str = "") -> str:
        from ..prompts import PROMPTS
        p = PROMPTS["equation_analysis"].format(
            entity_name=entity_name or Path(image_path).stem,
            equation_text=equation_text or "",
            equation_format=equation_format,
            context=context or "none",
        )
        return await self._call_vl(image_path, p)

    async def _call_vl(self, image_path: str, prompt: str) -> str:
        if not self.configured:
            return f"[VLM not configured] {prompt[:100]}..."
        self._ensure_client()
        try:
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


class LocalQwen2VLClient(VLMClient):
    """Local MinerU2.5-Pro/Qwen2-VL client backed by mineru_vl_utils."""

    def __init__(self, model_path: str = "", max_new_tokens: int = 256):
        default_path = Path(__file__).resolve().parents[3] / "models" / "MinerU2.5-Pro-2605-1.2B"
        configured_path = Path(model_path or os.getenv("QWEN_VL_LOCAL_MODEL_PATH", "")).expanduser()
        self.model_path = configured_path if str(configured_path) else default_path
        self.max_new_tokens = max_new_tokens
        self.model_name = self.model_path.name
        self.backend = os.getenv("QWEN_VL_LOCAL_BACKEND", "transformers")
        self._client = None

    @property
    def configured(self) -> bool:
        return self.model_path.exists()

    async def describe_image(self, image_path: str, prompt: str = "",
                              captions: str = "", footnotes: str = "",
                              context: str = "", entity_name: str = "") -> str:
        from ..prompts import PROMPTS
        final_prompt = prompt or PROMPTS["image_analysis"].format(
            entity_name=entity_name or Path(image_path).stem,
            captions=captions or "none",
            footnotes=footnotes or "none",
            context=context or "none",
        )
        return await asyncio.to_thread(self._call_local, image_path, final_prompt)

    async def describe_table(self, image_path: str, caption: str = "",
                              table_body: str = "", table_footnote: str = "",
                              context: str = "", entity_name: str = "") -> str:
        from ..prompts import PROMPTS
        prompt = PROMPTS["table_analysis"].format(
            entity_name=entity_name or Path(image_path).stem,
            table_caption=caption or "none",
            table_body=table_body or "none",
            table_footnote=table_footnote or "none",
            context=context or "none",
        )
        return await asyncio.to_thread(self._call_local, image_path, prompt)

    async def describe_equation(self, image_path: str, caption: str = "",
                                 equation_text: str = "", equation_format: str = "latex",
                                 context: str = "", entity_name: str = "") -> str:
        prompt = f"{equation_format}: {equation_text or caption or entity_name or Path(image_path).stem}"
        return await asyncio.to_thread(self._call_local, image_path, prompt)

    def _ensure_client(self) -> None:
        if self._client is not None:
            return

        from mineru_vl_utils import MinerUClient

        self._client = MinerUClient(
            backend=self.backend,
            model_path=str(self.model_path),
            image_analysis=True,
            use_tqdm=False,
            batch_size=int(os.getenv("QWEN_VL_LOCAL_BATCH_SIZE", "1")),
            debug=os.getenv("QWEN_VL_LOCAL_DEBUG", "") == "1",
        )

    def _call_local(self, image_path: str, prompt: str) -> str:
        if not self.configured:
            return f"[Local VLM not configured] {prompt[:100]}..."
        try:
            self._ensure_client()

            from PIL import Image

            image = Image.open(image_path).convert("RGB")
            result = self._client.two_step_extract(image)
            lines: list[str] = []
            for item in result:
                block_type = str(item.get("type", "")).strip()
                content = item.get("content", "")
                if isinstance(content, dict):
                    content = json.dumps(content, ensure_ascii=False)
                elif isinstance(content, list):
                    content = "\n".join(str(part).strip() for part in content if str(part).strip())
                text = str(content).strip()
                if not text:
                    continue
                lines.append(f"[{block_type}] {text}" if block_type else text)
            return "\n".join(lines).strip() if lines else f"[Local VLM empty] {prompt[:100]}..."
        except Exception as exc:
            return f"[Local VLM error: {exc}] {prompt[:100]}..."


def describe_vlm_runtime() -> dict[str, str | bool]:
    """Return the lightweight VLM runtime selection without loading the model."""
    mode = os.getenv("QWEN_VL_MODE", "api").strip().lower() or "api"
    local_backend = os.getenv("QWEN_VL_LOCAL_BACKEND", "transformers")
    local_path = Path(os.getenv("QWEN_VL_LOCAL_MODEL_PATH", "")).expanduser()
    default_local_path = Path(__file__).resolve().parents[3] / "models" / "MinerU2.5-Pro-2605-1.2B"
    selected_local_path = local_path if str(local_path) else default_local_path
    local_available = selected_local_path.exists()
    api_key = os.getenv("QWEN_VL_API_KEY", "")
    api_model = os.getenv("QWEN_VL_MODEL", "qwen-vl-max")

    if mode == "local":
        return {
            "configured": local_available,
            "mode": "local",
            "model": selected_local_path.name,
            "backend": local_backend,
        }
    if mode == "auto" and local_available:
        return {
            "configured": True,
            "mode": "local",
            "model": selected_local_path.name,
            "backend": local_backend,
        }
    if api_key:
        return {
            "configured": True,
            "mode": "api",
            "model": api_model,
            "backend": "openai-compatible",
        }
    if mode != "api" and local_available:
        return {
            "configured": True,
            "mode": "local",
            "model": selected_local_path.name,
            "backend": local_backend,
        }
    return {
        "configured": False,
        "mode": mode,
        "model": selected_local_path.name if mode != "api" else api_model,
        "backend": local_backend if mode != "api" else "openai-compatible",
    }


def build_vlm_client() -> VLMClient | None:
    runtime = describe_vlm_runtime()
    if runtime["mode"] == "local":
        client = LocalQwen2VLClient()
        return client if client.configured else None
    if runtime["mode"] == "auto":
        local_client = LocalQwen2VLClient()
        if local_client.configured:
            return local_client
    if os.getenv("QWEN_VL_API_KEY"):
        api_client = QwenVLClient()
        return api_client if api_client.configured else None
    if runtime["mode"] != "api":
        local_client = LocalQwen2VLClient()
        if local_client.configured:
            return local_client
    return None
