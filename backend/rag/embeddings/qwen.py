"""Qwen Embedding provider — Qwen3-Embedding via API or local model."""

from __future__ import annotations

from .base import BaseEmbeddingProvider


class QwenEmbeddingProvider(BaseEmbeddingProvider):
    """Qwen embedding models via OpenAI-compatible API.

    Supports: Qwen3-Embedding-0.6B, text-embedding-v3, etc.
    """

    def __init__(self, model_name: str = "Qwen/Qwen3-Embedding-0.6B",
                 base_url: str = "", api_key: str = ""):
        self._model_name = model_name
        self._base_url = base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self._api_key = api_key
        self._client = None
        self._dim = None

    @property
    def dimension(self) -> int:
        if self._dim is None:
            # try to infer from model name
            if "0.6b" in self._model_name.lower():
                self._dim = 1024
            elif "v3" in self._model_name.lower():
                self._dim = 1024
            else:
                self._dim = 1024
        return self._dim

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self._ensure_client()
        resp = self._client.embeddings.create(model=self._model_name, input=texts)
        return [d.embedding for d in resp.data]

    def configured(self) -> bool:
        return bool(self._api_key)

    def _ensure_client(self):
        if self._client is not None:
            return
        from openai import OpenAI
        self._client = OpenAI(base_url=self._base_url, api_key=self._api_key)
