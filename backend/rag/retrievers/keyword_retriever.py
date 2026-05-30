"""Keyword retriever — TF-IDF / BM25 for exact-match terms (frequency, footnote, standard)."""

from __future__ import annotations

from pathlib import Path

INDEX_DIR = Path(__file__).resolve().parents[3] / "data" / "knowledge_base" / "index"


class KeywordRetriever:
    """Keyword-based retrieval using the existing TF-IDF index.

    Specialized for exact-match queries: frequency numbers, footnote codes,
    standard identifiers — things that vector search may miss.
    """

    def __init__(self, top_k: int = 10):
        self.top_k = top_k
        self._vectorizer = None
        self._matrix = None

    def retrieve(self, query: str) -> list[dict]:
        self._ensure_loaded()

        from ...knowledge.store import SqliteStore
        store = SqliteStore()
        return store.search(query, top_k=self.top_k)

    def is_available(self) -> bool:
        return (INDEX_DIR / "vectorizer.pkl").exists()

    def _ensure_loaded(self):
        if not self.is_available():
            raise RuntimeError(
                "TF-IDF index not found. Run the knowledge base ingestion first."
            )
