"""Document registry with parse cache, status tracking, and resume support.

Aligned with RAG-Anything's parse cache + doc status pattern.
Uses JSON file at data/index/doc_registry.json for persistence.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import DOC_REGISTRY_PATH


def _load() -> dict:
    if DOC_REGISTRY_PATH.exists():
        return json.loads(DOC_REGISTRY_PATH.read_text())
    return {"docs": {}, "index_version": "v1", "embedding_model": "", "embedding_dim": 0}


def _save(data: dict):
    DOC_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_REGISTRY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _file_hash(path: str) -> str:
    """Stable hash from file content (first 64KB + size + mtime)."""
    st = os.stat(path)
    with open(path, "rb") as f:
        head = f.read(65536)
    raw = f"{head}{st.st_size}{st.st_mtime}".encode()
    return hashlib.md5(raw).hexdigest()[:16]


def register_doc(
    file_path: str,
    parser_name: str = "",
    parser_version: str = "",
    embedding_model: str = "",
    embedding_dim: int = 0,
    status: str = "indexing",
    metadata: dict | None = None,
):
    """Register a document in the registry with cache info."""
    reg = _load()
    doc_id = _file_hash(file_path)
    reg["docs"][doc_id] = {
        "file_path": file_path,
        "filename": os.path.basename(file_path),
        "content_hash": _file_hash(file_path),
        "parser_name": parser_name,
        "parser_version": parser_version,
        "embedding_model": embedding_model,
        "embedding_dim": embedding_dim,
        "status": status,  # indexing | indexed | failed
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "error": "",
        "metadata": metadata or {},
    }
    _save(reg)
    return doc_id


def update_status(doc_id: str, status: str, error: str = ""):
    reg = _load()
    if doc_id in reg["docs"]:
        reg["docs"][doc_id]["status"] = status
        if error:
            reg["docs"][doc_id]["error"] = error
        reg["docs"][doc_id]["indexed_at"] = datetime.now(timezone.utc).isoformat()
        _save(reg)


def is_cached(file_path: str, parser_name: str = "", parser_version: str = "") -> bool:
    """Check if a file has been parsed with the same config and hasn't changed."""
    reg = _load()
    doc_id = _file_hash(file_path)
    if doc_id not in reg["docs"]:
        return False
    info = reg["docs"][doc_id]
    if info.get("status") != "indexed":
        return False
    current_hash = _file_hash(file_path)
    if info.get("content_hash") != current_hash:
        return False
    if parser_name and info.get("parser_name") != parser_name:
        return False
    if parser_version and info.get("parser_version") != parser_version:
        return False
    return True


def get_unindexed(files: list[str], parser_name: str = "",
                  parser_version: str = "") -> list[str]:
    """Filter list of file paths, returning only those that need re-indexing."""
    return [f for f in files if not is_cached(f, parser_name, parser_version)]


def get_doc(doc_id: str) -> dict | None:
    return _load()["docs"].get(doc_id)


def list_docs(status: str | None = None) -> list[dict]:
    docs = list(_load()["docs"].values())
    if status:
        docs = [d for d in docs if d.get("status") == status]
    return docs


def doc_count() -> int:
    return len(_load()["docs"])
