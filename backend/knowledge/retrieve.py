"""Knowledge base retrieval — uses configured storage backend."""

from __future__ import annotations

from pathlib import Path

from .store import get_store, INDEX_DIR

_store = None


def _ensure_store():
    global _store
    if _store is None:
        _store = get_store()


def search(query: str, top_k: int = 5) -> list[dict]:
    """Search the knowledge base, return top-k chunks with source info."""
    _ensure_store()
    return _store.search(query, top_k)


def get_meta() -> dict:
    p = INDEX_DIR / "meta.json"
    if p.exists():
        import json
        with open(p) as f:
            return json.load(f)
    _ensure_store()
    n = _store.count()
    return {
        "status": "ready" if n > 0 else "not ingested",
        "total_chunks": n,
        "backend": _store.__class__.__name__,
    }


def is_ready() -> bool:
    if (INDEX_DIR / "vectorizer.pkl").exists():
        return True
    _ensure_store()
    return _store.count() > 0
