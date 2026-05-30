"""Abstract embedding provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseEmbeddingProvider(ABC):
    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, returning a list of embedding vectors."""
        ...

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string."""
        return self.embed_texts([query])[0]

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Embedding vector dimension."""
        ...
