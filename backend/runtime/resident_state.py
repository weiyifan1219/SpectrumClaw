from __future__ import annotations

import json
import mimetypes
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..rag.multimodal import describe_vlm_runtime
from ..rag.paths import CHROMA_DIR, DOC_REGISTRY_PATH, GRAPH_PATH, KB_RAW_DIR, PROJECT_ROOT

LOGS_DIR = PROJECT_ROOT / "logs"
DATA_DIR = PROJECT_ROOT / "data"
TFIDF_META_PATH = DATA_DIR / "knowledge_base" / "index" / "meta.json"
TFIDF_DB_PATH = DATA_DIR / "knowledge_base" / "kb.sqlite3"
CHROMA_DB_PATH = CHROMA_DIR / "chroma.sqlite3"

ARTIFACT_ROOTS = [
    ("parsed", DATA_DIR / "parsed"),
    ("knowledge_base", DATA_DIR / "knowledge_base"),
    ("evolution", DATA_DIR / "evolution"),
    ("eval", DATA_DIR / "eval"),
    ("mineru_cache", DATA_DIR / "mineru_cache"),
    ("run_backups", DATA_DIR / "run_backups"),
]

PREVIEWABLE_TEXT_EXTS = {
    ".md", ".txt", ".log", ".json", ".jsonl", ".ndjson",
    ".yaml", ".yml",
    ".csv", ".tsv", ".xml", ".html", ".py", ".sh", ".cfg", ".ini",
    ".toml", ".css", ".js", ".ts", ".jsx", ".tsx",
}
PREVIEWABLE_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}
PREVIEWABLE_PDF_EXTS = {".pdf"}
PREVIEWABLE_EXTS = PREVIEWABLE_TEXT_EXTS | PREVIEWABLE_IMAGE_EXTS | PREVIEWABLE_PDF_EXTS
PREVIEW_MAX_BYTES = 256 * 1024
LOG_LIST_TTL_SECONDS = 5
ARTIFACT_LIST_TTL_SECONDS = 10


@dataclass
class CacheEntry:
    signature: Any = None
    value: Any = None
    loaded_at: float = 0.0


@dataclass
class ResidentRuntimeState:
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _docs_cache: CacheEntry = field(default_factory=CacheEntry)
    _graph_cache: CacheEntry = field(default_factory=CacheEntry)
    _vector_cache: CacheEntry = field(default_factory=CacheEntry)
    _kb_cache: CacheEntry = field(default_factory=CacheEntry)
    _logs_cache: CacheEntry = field(default_factory=CacheEntry)
    _artifacts_cache: CacheEntry = field(default_factory=CacheEntry)
    _log_tail_cache: dict[tuple[str, int], CacheEntry] = field(default_factory=dict)
    _preview_cache: dict[str, CacheEntry] = field(default_factory=dict)
    _dirty: set[str] = field(default_factory=lambda: {"docs", "graph", "kb", "logs", "artifacts"})

    def warmup(self) -> None:
        self.list_docs()
        self.graph()
        self.kb_stats()
        self.list_logs()
        self.list_artifacts()

    def reset(self) -> None:
        with self._lock:
            self._docs_cache = CacheEntry()
            self._graph_cache = CacheEntry()
            self._vector_cache = CacheEntry()
            self._kb_cache = CacheEntry()
            self._logs_cache = CacheEntry()
            self._artifacts_cache = CacheEntry()
            self._log_tail_cache.clear()
            self._preview_cache.clear()
            self._dirty = {"docs", "graph", "kb", "logs", "artifacts"}

    def mark_rag_dirty(self) -> None:
        with self._lock:
            self._dirty.update({"docs", "graph", "kb", "artifacts"})

    def mark_logs_dirty(self) -> None:
        with self._lock:
            self._dirty.add("logs")

    def mark_artifacts_dirty(self) -> None:
        with self._lock:
            self._dirty.add("artifacts")

    def list_docs(self, status: str | None = None) -> list[dict[str, Any]]:
        docs = list(self._doc_registry()["docs"].values())
        if status:
            docs = [doc for doc in docs if doc.get("status") == status]
        return [dict(doc) for doc in docs]

    def graph(self) -> dict[str, Any]:
        graph = self._graph_data()
        return {
            "entities": [dict(entity) for entity in graph.get("entities", [])],
            "relations": [dict(relation) for relation in graph.get("relations", [])],
            "entity_count": graph.get("entity_count", 0),
            "relation_count": graph.get("relation_count", 0),
        }

    def kb_stats(self) -> dict[str, Any]:
        vlm_runtime = describe_vlm_runtime()
        signature = (
            self._file_signature(TFIDF_META_PATH),
            self._file_signature(TFIDF_DB_PATH),
            self._file_signature(DOC_REGISTRY_PATH),
            self._file_signature(GRAPH_PATH),
            self._file_signature(CHROMA_DB_PATH),
            self._file_signature(KB_RAW_DIR),
            vlm_runtime["configured"],
            vlm_runtime["mode"],
            vlm_runtime["model"],
            vlm_runtime["backend"],
        )
        with self._lock:
            if "kb" not in self._dirty and self._kb_cache.signature == signature:
                return dict(self._kb_cache.value or {})

        stats = self._base_kb_meta()
        graph = self._graph_data()
        docs = self._doc_registry()["docs"]
        vector_count = self._vector_count()

        stats["rag_pipeline"] = {
            "status": "ready" if CHROMA_DB_PATH.exists() else "not indexed",
            "vector_count": vector_count,
            "backend": "ChromaDB + sentence-transformers",
        }
        stats["knowledge_graph"] = {
            "status": "ready" if GRAPH_PATH.exists() else "not built",
            "entity_count": graph.get("entity_count", 0),
            "relation_count": graph.get("relation_count", 0),
            "entity_breakdown": self._entity_breakdown(graph.get("entities", [])),
            "relation_breakdown": self._entity_breakdown(graph.get("relations", []), key="relation"),
        }
        if docs:
            indexed = sum(1 for doc in docs.values() if doc.get("status") == "indexed")
            stats["total_pdfs"] = indexed or len(docs)
        elif not stats.get("total_pdfs") and KB_RAW_DIR.exists():
            stats["total_pdfs"] = sum(1 for _ in KB_RAW_DIR.glob("*.pdf"))
        stats["resident"] = {
            "loaded_at": time.time(),
            "vlm": dict(vlm_runtime),
        }

        with self._lock:
            self._kb_cache = CacheEntry(signature=signature, value=dict(stats), loaded_at=time.time())
            self._dirty.discard("kb")
        return stats

    def rag_status(self) -> dict[str, Any]:
        from ..rag.callbacks import get_ingest_events

        docs = self.list_docs()
        indexed = [doc for doc in docs if doc.get("status") == "indexed"]
        failed = [doc for doc in docs if doc.get("status") == "failed"]
        indexing = [doc for doc in docs if doc.get("status") == "indexing"]
        ingest = get_ingest_events()

        return {
            "registry": {
                "total": len(docs),
                "indexed": len(indexed),
                "failed": len(failed),
                "indexing": len(indexing),
            },
            "health": {"chroma": CHROMA_DB_PATH.exists(), "graph": GRAPH_PATH.exists()},
            "recent_failures": [
                {"file": doc.get("filename", ""), "error": doc.get("error", "")}
                for doc in failed[-10:]
            ],
            "ingest_progress": ingest.get("active"),
            "ingest_events": ingest.get("recent_events", [])[:20],
            "resident": {"loaded_at": time.time()},
        }

    def graph_entities(
        self,
        *,
        entity_type: str | None = None,
        search: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        graph = self._graph_data()
        entities = list(graph.get("entities", []))
        relations = list(graph.get("relations", []))

        if entity_type:
            entities = [entity for entity in entities if entity.get("type") == entity_type]
        if search:
            lowered = search.lower()
            entities = [entity for entity in entities if lowered in entity.get("name", "").lower()]

        entity_names = {entity.get("name", "") for entity in entities}
        filtered_relations = [
            dict(relation)
            for relation in relations
            if relation.get("source") in entity_names or relation.get("target") in entity_names
        ]

        return {
            "entities": [dict(entity) for entity in entities[:limit]],
            "relations": filtered_relations[: limit * 3],
            "total_entities": graph.get("entity_count", 0),
            "total_relations": graph.get("relation_count", 0),
        }

    def graph_entity(self, name: str) -> dict[str, Any]:
        graph = self._graph_data()
        entities = graph.get("entities", [])
        relations = graph.get("relations", [])
        entity = next((dict(item) for item in entities if item.get("name") == name), None)
        entity_map = {item.get("name"): item for item in entities}
        related = []
        for relation in relations:
            if relation.get("source") == name or relation.get("target") == name:
                item = dict(relation)
                item["source_type"] = entity_map.get(item.get("source"), {}).get("type", "")
                item["target_type"] = entity_map.get(item.get("target"), {}).get("type", "")
                related.append(item)
        return {"entity": entity, "relations": related}

    def list_logs(self) -> list[dict[str, Any]]:
        with self._lock:
            if "logs" not in self._dirty and time.time() - self._logs_cache.loaded_at < LOG_LIST_TTL_SECONDS:
                return [dict(item) for item in self._logs_cache.value or []]

        items: list[dict[str, Any]] = []
        if LOGS_DIR.is_dir():
            for file_path in sorted(LOGS_DIR.iterdir()):
                if not file_path.is_file():
                    continue
                stat = file_path.stat()
                items.append({
                    "name": file_path.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "lines": self._count_lines(file_path),
                })

        with self._lock:
            self._logs_cache = CacheEntry(signature=None, value=[dict(item) for item in items], loaded_at=time.time())
            self._dirty.discard("logs")
        return items

    def get_log(self, name: str, *, tail: int = 100) -> dict[str, Any]:
        path = LOGS_DIR / name
        if not path.is_file() or not is_safe_path(path, LOGS_DIR):
            raise FileNotFoundError(name)
        signature = (self._file_signature(path), tail)
        cache_key = (name, tail)

        with self._lock:
            cached = self._log_tail_cache.get(cache_key)
            if cached and cached.signature == signature:
                return dict(cached.value or {})

        payload = {
            "name": name,
            "size": path.stat().st_size,
            "modified": path.stat().st_mtime,
            "content": tail_lines(path, tail),
            "tail": tail,
        }
        with self._lock:
            self._log_tail_cache[cache_key] = CacheEntry(signature=signature, value=dict(payload), loaded_at=time.time())
        return payload

    def list_artifacts(
        self,
        *,
        category: str | None = None,
        search: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            if "artifacts" not in self._dirty and time.time() - self._artifacts_cache.loaded_at < ARTIFACT_LIST_TTL_SECONDS:
                items = [dict(item) for item in self._artifacts_cache.value or []]
            else:
                items = self._scan_artifacts()
                self._artifacts_cache = CacheEntry(signature=None, value=[dict(item) for item in items], loaded_at=time.time())
                self._dirty.discard("artifacts")

        if category:
            items = [item for item in items if item["category"] == category]
        if search:
            lowered = search.lower()
            items = [item for item in items if lowered in item["name"].lower()]
        return items[:limit]

    def artifact_preview(self, relative_path: str) -> dict[str, Any]:
        path = resolve_artifact_path(relative_path)
        if path is None or not path.is_file():
            raise FileNotFoundError(relative_path)
        ext = path.suffix.lower()
        if ext not in PREVIEWABLE_EXTS:
            raise ValueError(f"Preview not supported for {ext}")
        if path.stat().st_size > PREVIEW_MAX_BYTES:
            raise ValueError("File too large to preview (>256 KiB)")
        if ext not in PREVIEWABLE_TEXT_EXTS:
            raise ValueError("Binary preview is served via download endpoint")

        signature = self._file_signature(path)
        cache_key = relative_path
        with self._lock:
            cached = self._preview_cache.get(cache_key)
            if cached and cached.signature == signature:
                return dict(cached.value or {})

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("File is not valid UTF-8 text") from exc

        payload = {
            "path": rel_path(path),
            "name": path.name,
            "size": path.stat().st_size,
            "content": content,
        }
        with self._lock:
            self._preview_cache[cache_key] = CacheEntry(signature=signature, value=dict(payload), loaded_at=time.time())
        return payload

    def rag_health(self) -> dict[str, Any]:
        doc_count = len(self.list_docs())
        graph_size = GRAPH_PATH.stat().st_size if GRAPH_PATH.exists() else 0
        vector_count = self._vector_count()
        registry_status = "ok" if DOC_REGISTRY_PATH.exists() and doc_count >= 0 else "warn"
        vector_status = "ok" if CHROMA_DB_PATH.exists() else "warn"
        graph_status = "ok" if GRAPH_PATH.exists() else "warn"
        overall = "ok" if registry_status == vector_status == graph_status == "ok" else "warn"

        return {
            "overall_status": overall,
            "doc_registry": rel_path(DOC_REGISTRY_PATH),
            "doc_count": doc_count,
            "registry_status": registry_status,
            "registry_value": f"{doc_count} docs" if DOC_REGISTRY_PATH.exists() else "未注册",
            "registry_detail": rel_path(DOC_REGISTRY_PATH),
            "vector_status": vector_status,
            "vector_value": f"{vector_count} vectors" if CHROMA_DB_PATH.exists() else "missing",
            "vector_detail": rel_path(CHROMA_DB_PATH),
            "graph_status": graph_status,
            "graph_value": format_bytes(graph_size) if graph_size else "missing",
            "graph_detail": rel_path(GRAPH_PATH),
        }

    def artifact_health(self) -> dict[str, Any]:
        artifacts = self.list_artifacts(limit=1000)
        existing_roots = [label for label, path in ARTIFACT_ROOTS if path.exists()]
        logs = self.list_logs()
        return {
            "status": "ok" if existing_roots else "warn",
            "roots": existing_roots,
            "logs": f"{len(logs)} files" if LOGS_DIR.exists() else "missing",
            "value": f"{len(existing_roots)}/{len(ARTIFACT_ROOTS)} roots",
            "detail": ", ".join(existing_roots) if existing_roots else "no artifact roots found",
            "artifact_count": len(artifacts),
        }

    def _doc_registry(self) -> dict[str, Any]:
        signature = self._file_signature(DOC_REGISTRY_PATH)
        with self._lock:
            if "docs" not in self._dirty and self._docs_cache.signature == signature:
                return dict(self._docs_cache.value or {"docs": {}})

        if DOC_REGISTRY_PATH.exists():
            try:
                value = json.loads(DOC_REGISTRY_PATH.read_text(encoding="utf-8"))
            except Exception:
                value = {"docs": {}, "index_version": "v1", "embedding_model": "", "embedding_dim": 0}
        else:
            value = {"docs": {}, "index_version": "v1", "embedding_model": "", "embedding_dim": 0}
        if not isinstance(value.get("docs"), dict):
            value["docs"] = {}

        with self._lock:
            self._docs_cache = CacheEntry(signature=signature, value=dict(value), loaded_at=time.time())
            self._dirty.discard("docs")
        return value

    def _graph_data(self) -> dict[str, Any]:
        signature = self._file_signature(GRAPH_PATH)
        with self._lock:
            if "graph" not in self._dirty and self._graph_cache.signature == signature:
                return dict(self._graph_cache.value or {"entities": [], "relations": [], "entity_count": 0, "relation_count": 0})

        if GRAPH_PATH.exists():
            try:
                value = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
            except Exception:
                value = {"entities": [], "relations": [], "entity_count": 0, "relation_count": 0}
        else:
            value = {"entities": [], "relations": [], "entity_count": 0, "relation_count": 0}
        value.setdefault("entities", [])
        value.setdefault("relations", [])
        value.setdefault("entity_count", len(value["entities"]))
        value.setdefault("relation_count", len(value["relations"]))

        with self._lock:
            self._graph_cache = CacheEntry(signature=signature, value=dict(value), loaded_at=time.time())
            self._dirty.discard("graph")
        return value

    def _vector_count(self) -> int:
        signature = self._file_signature(CHROMA_DB_PATH)
        with self._lock:
            if self._vector_cache.signature == signature:
                return int(self._vector_cache.value or 0)

        if not CHROMA_DB_PATH.exists():
            count = 0
        else:
            try:
                with sqlite3.connect(str(CHROMA_DB_PATH)) as db:
                    count = int(db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0])
            except Exception:
                count = 0

        with self._lock:
            self._vector_cache = CacheEntry(signature=signature, value=count, loaded_at=time.time())
        return count

    def _base_kb_meta(self) -> dict[str, Any]:
        if TFIDF_META_PATH.exists():
            try:
                return json.loads(TFIDF_META_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        total_chunks = 0
        if TFIDF_DB_PATH.exists():
            try:
                with sqlite3.connect(str(TFIDF_DB_PATH)) as db:
                    total_chunks = int(db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
            except Exception:
                total_chunks = 0
        return {
            "status": "ready" if total_chunks > 0 else "not ingested",
            "total_chunks": total_chunks,
            "backend": "SqliteStore",
        }

    def _scan_artifacts(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for category, root in ARTIFACT_ROOTS:
            if not root.is_dir():
                continue
            for file_path in root.rglob("*"):
                if not file_path.is_file():
                    continue
                stat = file_path.stat()
                ext = file_path.suffix.lower()
                items.append({
                    "name": file_path.name,
                    "path": rel_path(file_path),
                    "category": category,
                    "type": ext.lstrip(".").upper() if ext else "FILE",
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "previewable": ext in PREVIEWABLE_EXTS,
                    "preview_type": (
                        "image" if ext in PREVIEWABLE_IMAGE_EXTS
                        else "pdf" if ext in PREVIEWABLE_PDF_EXTS
                        else "text" if ext in PREVIEWABLE_TEXT_EXTS
                        else None
                    ),
                })
        items.sort(key=lambda item: item["modified"], reverse=True)
        return items

    @staticmethod
    def _file_signature(path: Path) -> tuple[bool, int, int]:
        if not path.exists():
            return (False, 0, 0)
        try:
            stat = path.stat()
        except OSError:
            return (False, 0, 0)
        return (True, stat.st_mtime_ns, stat.st_size)

    @staticmethod
    def _entity_breakdown(items: list[dict[str, Any]], *, key: str = "type") -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for item in items:
            item_key = str(item.get(key, "Unknown"))
            counts[item_key] = counts.get(item_key, 0) + 1
        return [
            {"type": item_key, "count": count}
            for item_key, count in sorted(counts.items(), key=lambda pair: pair[1], reverse=True)
        ]

    @staticmethod
    def _count_lines(path: Path) -> int:
        try:
            with open(path, "rb") as handle:
                return sum(1 for _ in handle)
        except Exception:
            return 0


_resident_state = ResidentRuntimeState()


def get_resident_state() -> ResidentRuntimeState:
    return _resident_state


def rel_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def is_safe_path(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def is_sensitive_artifact_path(path: Path) -> bool:
    lowered_parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    if any(part.startswith(".") for part in path.parts):
        return True
    if name in {".env", "id_rsa", "id_ed25519"}:
        return True
    if any(token in name for token in ("secret", "token", "credential", "apikey", "api_key")):
        return True
    return any(part in {"__pycache__", ".git"} for part in lowered_parts)


def resolve_artifact_path(relative_path: str) -> Path | None:
    candidate = (PROJECT_ROOT / relative_path).resolve()
    if is_sensitive_artifact_path(candidate):
        return None
    for _, root in ARTIFACT_ROOTS:
        if is_safe_path(candidate, root):
            return candidate
    return None


def tail_lines(path: Path, line_count: int) -> str:
    size = path.stat().st_size
    if size < 128 * 1024:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
        return "".join(lines[-line_count:])

    with open(path, "rb") as handle:
        estimated_line_bytes = max(size // max(count_lines_fast(path), 1), 80)
        start = max(0, size - line_count * estimated_line_bytes * 2)
        handle.seek(start)
        raw = handle.read()
    text = raw.decode("utf-8", errors="replace")
    return "".join(text.splitlines(keepends=True)[-line_count:])


def count_lines_fast(path: Path) -> int:
    try:
        with open(path, "rb") as handle:
            chunk = handle.read(65536)
        return max(chunk.count(b"\n"), 1)
    except Exception:
        return 1000


def guess_media_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


def format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"
