"""Embedding provider abstractions and implementations."""

from .base import BaseEmbeddingProvider
from .sentence_transformer import SentenceTransformersEmbeddingProvider

__all__ = ["BaseEmbeddingProvider", "SentenceTransformersEmbeddingProvider"]
