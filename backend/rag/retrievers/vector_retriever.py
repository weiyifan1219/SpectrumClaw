"""Vector retriever — semantic search via Chroma."""

from __future__ import annotations

from ..vectorstores.chroma_store import ChromaStore


class VectorRetriever:
    """Retrieve top-k blocks from the Chroma vector store."""

    def __init__(self, store: ChromaStore, top_k: int = 10):
        self._store = store
        self.top_k = top_k

    def retrieve(self, query: str, where: dict | None = None) -> list[dict]:
        """Search and return blocks with metadata and scores."""
        return self._store.search(query, top_k=self.top_k, where=where)

    @property
    def store(self) -> ChromaStore:
        return self._store
