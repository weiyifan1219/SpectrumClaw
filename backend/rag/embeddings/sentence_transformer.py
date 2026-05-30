"""Sentence-Transformers based embedding provider."""

from __future__ import annotations

from .base import BaseEmbeddingProvider


class SentenceTransformersEmbeddingProvider(BaseEmbeddingProvider):
    """Local embedding via sentence-transformers.

    Default model: all-MiniLM-L6-v2 (384-dim, fast, good for English).
    For Chinese-heavy docs, switch to BAAI/bge-small-zh-v1.5 or similar.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: str = "cpu"):
        self._model_name = model_name
        self._device = device
        self._model = None

    @property
    def dimension(self) -> int:
        self._ensure_model()
        return self._model.get_sentence_embedding_dimension()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self._ensure_model()
        embeddings = self._model.encode(
            texts,
            batch_size=32,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]

    def _ensure_model(self):
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self._model_name, device=self._device)
