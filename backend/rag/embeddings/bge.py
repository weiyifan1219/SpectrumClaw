"""BGE Embedding provider — BAAI/bge-m3, bge-large, etc."""

from __future__ import annotations

from .base import BaseEmbeddingProvider


class BGEEmbeddingProvider(BaseEmbeddingProvider):
    """BGE model embedding via sentence-transformers.

    Supports bge-m3 (1024-dim, multilingual), bge-large-en (1024-dim, English).
    """

    def __init__(self, model_name: str = "BAAI/bge-m3", device: str = "cpu"):
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
            texts, batch_size=32, show_progress_bar=False,
            convert_to_numpy=True, normalize_embeddings=True,
        )
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([f"Represent this sentence for searching relevant passages: {query}"])[0]

    def configured(self) -> bool:
        try:
            from sentence_transformers import SentenceTransformer
            return True
        except ImportError:
            return False

    def _ensure_model(self):
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self._model_name, device=self._device)
