"""OpenAI Embedding provider — text-embedding-3-large, text-embedding-3-small, etc."""

from __future__ import annotations

from .base import BaseEmbeddingProvider


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI embedding models via API.

    Supports: text-embedding-3-large (3072-dim), text-embedding-3-small (1536-dim).
    """

    def __init__(self, model_name: str = "text-embedding-3-large",
                 base_url: str = "", api_key: str = ""):
        self._model_name = model_name
        self._base_url = base_url or "https://api.openai.com/v1"
        self._api_key = api_key
        self._client = None

    @property
    def dimension(self) -> int:
        if "large" in self._model_name:
            return 3072
        if "small" in self._model_name:
            return 1536
        return 1536

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
