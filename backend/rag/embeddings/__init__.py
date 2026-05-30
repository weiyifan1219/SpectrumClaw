"""Embedding providers — pluggable sentence-transformers, BGE, Qwen, OpenAI."""

from .base import BaseEmbeddingProvider
from .sentence_transformer import SentenceTransformersEmbeddingProvider
from .bge import BGEEmbeddingProvider
from .qwen import QwenEmbeddingProvider
from .openai_provider import OpenAIEmbeddingProvider

_providers = {
    "sentence-transformers": SentenceTransformersEmbeddingProvider,
    "bge": BGEEmbeddingProvider,
    "qwen": QwenEmbeddingProvider,
    "openai": OpenAIEmbeddingProvider,
}


def get_embedding_provider(
    provider: str = "sentence-transformers",
    model_name: str = "",
    **kwargs,
) -> BaseEmbeddingProvider:
    """Factory: create embedding provider by name. Falls back to sentence-transformers."""
    cls = _providers.get(provider, SentenceTransformersEmbeddingProvider)
    if model_name:
        return cls(model_name=model_name, **kwargs)
    return cls(**kwargs)


def list_providers() -> list[str]:
    return list(_providers.keys())


__all__ = [
    "BaseEmbeddingProvider",
    "SentenceTransformersEmbeddingProvider",
    "BGEEmbeddingProvider",
    "QwenEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "get_embedding_provider", "list_providers",
]
