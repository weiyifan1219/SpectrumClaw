"""Sentence-Transformers based embedding provider with offline fallback."""

from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path

from .base import BaseEmbeddingProvider


class HashingEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic local embedding fallback for offline server validation.

    This is not a replacement for a trained embedding model, but it keeps the
    RAG ingest/search path functional when the deployment host cannot download
    sentence-transformers weights.
    """

    def __init__(self, dimension: int = 384):
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dimension
        tokens = re.findall(r"[\w.:-]+", text.lower())
        for token in tokens:
            digest = hashlib.md5(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "little") % self._dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign

        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]


class SentenceTransformersEmbeddingProvider(BaseEmbeddingProvider):
    """Local embedding via sentence-transformers.

    Default model: all-MiniLM-L6-v2 (384-dim, fast, good for English).
    For Chinese-heavy docs, switch to BAAI/bge-small-zh-v1.5 or similar.
    """

    def __init__(self, model_name: str | None = None, device: str | None = None):
        model_name = model_name or self._default_model_name()
        device = device or os.getenv("SPECTRUMCLAW_EMBEDDING_DEVICE", "cpu")
        self._model_name = model_name
        self._device = device
        self._model = None
        self._fallback_model: HashingEmbeddingProvider | None = None

    @property
    def dimension(self) -> int:
        self._ensure_model()
        if self._fallback_model is not None:
            return self._fallback_model.dimension
        return self._model.get_sentence_embedding_dimension()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self._ensure_model()
        if self._fallback_model is not None:
            return self._fallback_model.embed_texts(texts)
        batch_size = int(os.getenv("SPECTRUMCLAW_EMBEDDING_BATCH", "32"))
        embeddings = self._model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]

    def _ensure_model(self):
        if self._model is not None or self._fallback_model is not None:
            return
        from sentence_transformers import SentenceTransformer
        try:
            self._model = SentenceTransformer(self._model_name, device=self._device)
            # Cap sequence length so a few pathologically long blocks (tens of
            # thousands of chars) can't blow up GPU memory via the O(n^2)
            # attention matrix. bge-m3 supports up to 8192 tokens.
            max_seq = int(os.getenv("SPECTRUMCLAW_EMBEDDING_MAX_SEQ", "2048"))
            try:
                self._model.max_seq_length = max_seq
            except Exception:
                pass
        except Exception:
            if os.getenv("SPECTRUMCLAW_EMBEDDING_FALLBACK", "hash").lower() != "hash":
                raise
            dim = int(os.getenv("SPECTRUMCLAW_HASH_EMBEDDING_DIM", "384"))
            self._fallback_model = HashingEmbeddingProvider(dimension=dim)

    @staticmethod
    def _default_model_name() -> str:
        configured = os.getenv("SPECTRUMCLAW_EMBEDDING_MODEL")
        if configured:
            return configured

        project_root = Path(__file__).resolve().parents[3]
        for name in ("bge-m3", "bge-small-en-v1.5"):
            local_model = project_root / "models" / "embeddings" / name
            if _looks_like_sentence_transformer_model(local_model):
                return str(local_model)
        return "BAAI/bge-m3"


def _looks_like_sentence_transformer_model(path: Path) -> bool:
    if not path.exists():
        return False
    has_weight = any((path / filename).exists() for filename in (
        "pytorch_model.bin",
        "model.safetensors",
    ))
    return has_weight and (path / "modules.json").exists()
