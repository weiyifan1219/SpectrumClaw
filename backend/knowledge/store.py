"""Knowledge base storage backends.

Interface: each backend implements:
- insert(chunks: list[dict]) -> int          # returns count inserted
- search(query_vector, top_k: int) -> list[dict]  # returns [{source, text, score}, ...]
- count() -> int
- clear()

Environment variable SPECTRUMCLAW_KB_BACKEND selects the backend:
- "sqlite" (default)  — local SQLite
- "postgres" (future) — remote PostgreSQL + pgvector
- "qdrant"  (future) — Qdrant vector database
"""

from __future__ import annotations

import json
import os
import pickle
import sqlite3
from pathlib import Path

import numpy as np

INDEX_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge_base" / "index"
DB_PATH = Path(__file__).resolve().parents[2] / "data" / "knowledge_base" / "kb.sqlite3"


class SqliteStore:
    """Local SQLite storage with in-memory TF-IDF vectors."""

    def __init__(self, db_path: Path | None = None, index_dir: Path | None = None):
        self.db_path = db_path or DB_PATH
        self.index_dir = index_dir or INDEX_DIR

    def insert(self, chunks: list[dict]) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self.db_path.unlink()
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chunks ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  source TEXT NOT NULL,"
            "  text TEXT NOT NULL"
            ")"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON chunks(source)")
        conn.executemany(
            "INSERT INTO chunks (source, text) VALUES (?, ?)",
            [(c["source"], c["text"]) for c in chunks],
        )
        conn.commit()
        conn.close()
        return len(chunks)

    def search(self, query_vector, top_k: int = 5) -> list[dict]:
        if not self.index_dir.exists():
            return []
        if isinstance(query_vector, str):
            with open(self.index_dir / "vectorizer.pkl", "rb") as f:
                vec = pickle.load(f)
            import scipy.sparse
            matrix = scipy.sparse.load_npz(str(self.index_dir / "tfidf_matrix.npz"))
            qv = vec.transform([query_vector])
            scores = (matrix @ qv.T).toarray().flatten()
        else:
            scores = query_vector

        with open(self.index_dir / "chunk_sources.json") as f:
            sources = json.load(f)
        with open(self.index_dir / "chunk_texts.json") as f:
            texts = json.load(f)

        top = np.argsort(scores)[::-1][:top_k]
        return [
            {"source": sources[i], "text": texts[i][:1200], "score": round(float(scores[i]), 4)}
            for i in top if scores[i] > 0.01
        ]

    def count(self) -> int:
        if not self.db_path.exists():
            return 0
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.execute("SELECT COUNT(*) FROM chunks")
        n = cur.fetchone()[0]
        conn.close()
        return n

    def clear(self):
        if self.db_path.exists():
            self.db_path.unlink()


class PostgresStore:
    """PostgreSQL + pgvector backend (future)."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.getenv("SPECTRUMCLAW_KB_DSN", "")

    def insert(self, chunks: list[dict]) -> int:
        raise NotImplementedError("Postgres backend not yet implemented")

    def search(self, query_vector, top_k: int = 5) -> list[dict]:
        raise NotImplementedError("Postgres backend not yet implemented")

    def count(self) -> int:
        raise NotImplementedError("Postgres backend not yet implemented")

    def clear(self):
        raise NotImplementedError("Postgres backend not yet implemented")


class QdrantStore:
    """Qdrant vector database backend (future)."""

    def __init__(self, url: str | None = None, api_key: str | None = None):
        self.url = url or os.getenv("SPECTRUMCLAW_QDRANT_URL", "")
        self.api_key = api_key or os.getenv("SPECTRUMCLAW_QDRANT_API_KEY", "")

    def insert(self, chunks: list[dict]) -> int:
        raise NotImplementedError("Qdrant backend not yet implemented")

    def search(self, query_vector, top_k: int = 5) -> list[dict]:
        raise NotImplementedError("Qdrant backend not yet implemented")

    def count(self) -> int:
        raise NotImplementedError("Qdrant backend not yet implemented")

    def clear(self):
        raise NotImplementedError("Qdrant backend not yet implemented")


def get_store() -> SqliteStore:
    """Factory: return the configured knowledge base backend."""
    backend = os.getenv("SPECTRUMCLAW_KB_BACKEND", "sqlite")
    if backend == "postgres":
        return PostgresStore()
    if backend == "qdrant":
        return QdrantStore()
    return SqliteStore()
