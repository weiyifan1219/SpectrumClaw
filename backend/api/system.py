"""Read-only endpoints for logs and output artifacts.

Intentionally minimal — list + tail logs, browse + preview + download artifacts.
Does not mutate anything; safe to use while mineru / RAG pipelines are running.
"""

from __future__ import annotations

import json
import os
import mimetypes
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse

from ..config import get_settings
from ..rag.paths import CHROMA_DIR, DOC_REGISTRY_PATH, GRAPH_PATH

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # SpectrumClaw/
LOGS_DIR = PROJECT_ROOT / "logs"
DATA_DIR = PROJECT_ROOT / "data"

PREVIEWABLE_TEXT_EXTS = {
    ".md", ".txt", ".log", ".json", ".jsonl", ".ndjson",
    ".yaml", ".yml",
    ".csv", ".tsv", ".xml", ".html", ".py", ".sh", ".cfg", ".ini",
    ".toml", ".css", ".js", ".ts", ".jsx", ".tsx",
}
PREVIEWABLE_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}
PREVIEWABLE_PDF_EXTS = {".pdf"}
PREVIEWABLE_EXTS = PREVIEWABLE_TEXT_EXTS | PREVIEWABLE_IMAGE_EXTS | PREVIEWABLE_PDF_EXTS
PREVIEW_MAX_BYTES = 256 * 1024  # 256 KiB for text; images/pdf served directly


def _rel(path: Path) -> str:
    """Path relative to PROJECT_ROOT, using forward slashes."""
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


# ── Logs ──────────────────────────────────────────────────────────────

@router.get("/api/system/logs")
async def list_logs():
    """List available log files in logs/ with metadata."""
    items = []
    if LOGS_DIR.is_dir():
        for f in sorted(LOGS_DIR.iterdir()):
            if not f.is_file():
                continue
            stat = f.stat()
            # count lines cheaply for small/medium logs
            try:
                with open(f, "rb") as fh:
                    lines = sum(1 for _ in fh)
            except Exception:
                lines = 0
            items.append({
                "name": f.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "lines": lines,
            })
    return {"logs": items}


@router.get("/api/system/logs/{name}")
async def get_log(
    name: str,
    tail: int = Query(100, ge=1, le=5000, description="Return last N lines"),
    download: bool = Query(False, description="Download as text file"),
):
    """Fetch log file content, defaulting to the last `tail` lines."""
    path = LOGS_DIR / name
    if not path.is_file() or not _is_safe_path(path, LOGS_DIR):
        raise HTTPException(status_code=404, detail=f"Log not found: {name}")

    if download:
        return FileResponse(
            path, media_type="text/plain; charset=utf-8",
            filename=name,
        )

    content = _tail_lines(path, tail)
    return {
        "name": name,
        "size": path.stat().st_size,
        "modified": path.stat().st_mtime,
        "content": content,
        "tail": tail,
    }


# ── Artifacts ─────────────────────────────────────────────────────────

_ARTIFACT_ROOTS = [
    ("parsed", DATA_DIR / "parsed"),
    ("knowledge_base", DATA_DIR / "knowledge_base"),
    ("evolution", DATA_DIR / "evolution"),
    ("eval", DATA_DIR / "eval"),
    ("mineru_cache", DATA_DIR / "mineru_cache"),
    ("run_backups", DATA_DIR / "run_backups"),
]


@router.get("/api/system/health/deep")
async def deep_health():
    """Return a lightweight health snapshot for the operating dashboard."""
    settings = get_settings()
    provider = settings.provider_profile()
    memory_path = (PROJECT_ROOT / settings.memory_db_path).resolve()
    sidecar_url = _genspectra_sidecar_url()

    memory = _check_sqlite(memory_path)
    rag = _rag_health()
    sidecar = await _http_health(sidecar_url.rstrip("/") + "/health")
    artifacts = _artifact_health()

    checks = [
        _check("Runtime", "API Service", "ok", "FastAPI online", f"{settings.env} · {settings.agent_runtime}"),
        _check("Runtime", "Project Root", "ok" if PROJECT_ROOT.exists() else "error", _rel(PROJECT_ROOT), "workspace"),
        _check(
            "External",
            "LLM Provider",
            "ok" if provider.configured else "warn",
            f"{provider.provider} · {provider.model or '未配置'}",
            provider.api_type,
        ),
        _check("Storage", "Memory DB", memory["status"], memory["value"], memory["detail"]),
        _check("Storage", "RAG Registry", rag["registry_status"], rag["registry_value"], rag["registry_detail"]),
        _check("Storage", "Vector Store", rag["vector_status"], rag["vector_value"], rag["vector_detail"]),
        _check("Storage", "Knowledge Graph", rag["graph_status"], rag["graph_value"], rag["graph_detail"]),
        _check("Service", "GenSpectra Sidecar", sidecar["status"], sidecar["value"], sidecar["detail"]),
        _check("Service", "Logs", "ok" if LOGS_DIR.exists() else "warn", artifacts["logs"], _rel(LOGS_DIR)),
        _check("Service", "Artifacts", artifacts["status"], artifacts["value"], artifacts["detail"]),
    ]

    return {
        "generated_at": time.time(),
        "summary": [
            {
                "key": "Backend",
                "value": "Online",
                "detail": f"{settings.env} · {settings.agent_runtime}",
                "tone": "ok",
            },
            {
                "key": "Model",
                "value": provider.model if provider.configured else "未配置",
                "detail": f"{provider.provider} · {provider.api_type}",
                "tone": "ok" if provider.configured else "warn",
            },
            {
                "key": "Knowledge",
                "value": rag["registry_value"],
                "detail": rag["graph_value"],
                "tone": _tone_for_status(rag["overall_status"]),
            },
        ],
        "backend": {
            "status": "ok",
            "env": settings.env,
            "agent_runtime": settings.agent_runtime,
            "project_root": PROJECT_ROOT.name,
        },
        "llm": {
            "status": "ok" if provider.configured else "warn",
            "configured": provider.configured,
            "provider": provider.provider,
            "api_type": provider.api_type,
            "model": provider.model if provider.configured else "",
        },
        "memory": memory,
        "rag": rag,
        "sidecar": sidecar,
        "artifacts": artifacts,
        "checks": checks,
    }


@router.get("/api/system/artifacts")
async def list_artifacts(
    category: str | None = Query(None, description="Filter by category"),
    search: str | None = Query(None, description="Filter filename substring"),
    limit: int = Query(100, ge=1, le=1000),
):
    """List output artifacts (files) across data/ directories, newest first."""
    items = []
    for cat_label, cat_dir in _ARTIFACT_ROOTS:
        if category and cat_label != category:
            continue
        if not cat_dir.is_dir():
            continue
        for f in cat_dir.rglob("*"):
            if not f.is_file():
                continue
            if search and search.lower() not in f.name.lower():
                continue
            stat = f.stat()
            ext = f.suffix.lower()
            items.append({
                "name": f.name,
                "path": _rel(f),
                "category": cat_label,
                "type": ext.lstrip(".").upper() if ext else "FILE",
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "previewable": ext in PREVIEWABLE_EXTS,
                "preview_type": "image" if ext in PREVIEWABLE_IMAGE_EXTS else "pdf" if ext in PREVIEWABLE_PDF_EXTS else "text" if ext in PREVIEWABLE_TEXT_EXTS else None,
            })
    # global sort by modification time — newest first
    items.sort(key=lambda x: x["modified"], reverse=True)
    items = items[:limit]
    return {"artifacts": items}


@router.get("/api/system/artifacts/preview/{filepath:path}")
async def preview_artifact(filepath: str):
    """Return text content of a previewable artifact."""
    path = _safe_resolve(filepath)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {filepath}")
    ext = path.suffix.lower()
    if ext not in PREVIEWABLE_EXTS:
        raise HTTPException(status_code=400, detail=f"Preview not supported for {ext}")
    if path.stat().st_size > PREVIEW_MAX_BYTES:
        raise HTTPException(status_code=400, detail="File too large to preview (>256 KiB)")
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File is not valid UTF-8 text")
    return {
        "path": _rel(path),
        "name": path.name,
        "size": path.stat().st_size,
        "content": content,
    }


@router.get("/api/system/artifacts/download/{filepath:path}")
async def download_artifact(
    filepath: str,
    inline: bool = Query(False, description="Serve inline (preview) instead of download"),
):
    """Download or inline-view any artifact file."""
    path = _safe_resolve(filepath)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {filepath}")
    mime, _ = mimetypes.guess_type(path.name)
    kwargs: dict = {"media_type": mime or "application/octet-stream"}
    if not inline:
        kwargs["filename"] = path.name  # triggers Content-Disposition: attachment
    return FileResponse(path, **kwargs)


# ── helpers ───────────────────────────────────────────────────────────

def _is_safe_path(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_resolve(relative: str) -> Path | None:
    """Resolve a relative artifact path; reject escapes and non-artifact files."""
    candidate = (PROJECT_ROOT / relative).resolve()
    if _is_sensitive_artifact_path(candidate):
        return None
    for _, root in _ARTIFACT_ROOTS:
        if _is_safe_path(candidate, root):
            return candidate
    return None


def _tail_lines(path: Path, n: int) -> str:
    """Return approximately the last n lines without reading whole file."""
    size = path.stat().st_size
    # if file is small, just read it all
    if size < 128 * 1024:  # 128 KiB
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        return "".join(lines[-n:])
    # for larger files, seek back and read (simple ring-buffer approach)
    with open(path, "rb") as fh:
        # start from estimated position
        est_line_bytes = max(size // max(_count_lines_fast(path), 1), 80)
        start = max(0, size - n * est_line_bytes * 2)
        fh.seek(start)
        raw = fh.read()
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    return "".join(lines[-n:])


def _count_lines_fast(path: Path) -> int:
    """Quick rough line count for estimation."""
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(65536)
            return max(chunk.count(b"\n"), 1)
    except Exception:
        return 1000


def _check(group: str, name: str, status: str, value: str, detail: str = "") -> dict[str, str]:
    return {
        "group": group,
        "name": name,
        "status": status,
        "tone": _tone_for_status(status),
        "value": value,
        "detail": detail,
    }


def _tone_for_status(status: str) -> str:
    return {
        "ok": "ok",
        "warn": "warn",
        "error": "warn",
        "offline": "muted",
        "unknown": "info",
    }.get(status, "info")


def _check_sqlite(path: Path) -> dict[str, Any]:
    rel_path = _rel(path)
    if not path.exists():
        return {
            "status": "warn",
            "path": rel_path,
            "exists": False,
            "size": 0,
            "value": "未创建",
            "detail": rel_path,
        }
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1) as conn:
            conn.execute("select 1").fetchone()
    except sqlite3.Error as exc:
        return {
            "status": "error",
            "path": rel_path,
            "exists": True,
            "size": path.stat().st_size,
            "value": "不可读",
            "detail": exc.__class__.__name__,
        }
    return {
        "status": "ok",
        "path": rel_path,
        "exists": True,
        "size": path.stat().st_size,
        "value": _format_bytes(path.stat().st_size),
        "detail": rel_path,
    }


def _rag_health() -> dict[str, Any]:
    doc_count = _doc_registry_count(DOC_REGISTRY_PATH)
    graph_size = GRAPH_PATH.stat().st_size if GRAPH_PATH.exists() else 0
    chroma_db = CHROMA_DIR / "chroma.sqlite3"
    chroma_exists = chroma_db.is_file()

    registry_status = "ok" if DOC_REGISTRY_PATH.exists() and doc_count is not None else "warn"
    vector_status = "ok" if chroma_exists else "warn"
    graph_status = "ok" if GRAPH_PATH.exists() else "warn"
    overall = "ok" if registry_status == vector_status == graph_status == "ok" else "warn"

    return {
        "overall_status": overall,
        "doc_registry": _rel(DOC_REGISTRY_PATH),
        "doc_count": doc_count,
        "registry_status": registry_status,
        "registry_value": f"{doc_count} docs" if doc_count is not None else "未注册",
        "registry_detail": _rel(DOC_REGISTRY_PATH),
        "vector_status": vector_status,
        "vector_value": "ready" if chroma_exists else "missing",
        "vector_detail": _rel(chroma_db),
        "graph_status": graph_status,
        "graph_value": _format_bytes(graph_size) if graph_size else "missing",
        "graph_detail": _rel(GRAPH_PATH),
    }


def _doc_registry_count(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("documents", "docs", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
            if isinstance(value, dict):
                return len(value)
        return len(data)
    return None


async def _http_health(url: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=1) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
        if 200 <= resp.status_code < 300:
            return {"status": "ok", "value": "online", "detail": "health endpoint"}
        return {"status": "warn", "value": f"HTTP {resp.status_code}", "detail": "health endpoint"}
    except (httpx.HTTPError, OSError) as exc:
        return {"status": "offline", "value": "offline", "detail": exc.__class__.__name__}


def _artifact_health() -> dict[str, Any]:
    existing_roots = [label for label, path in _ARTIFACT_ROOTS if path.exists()]
    log_count = len([p for p in LOGS_DIR.iterdir() if p.is_file()]) if LOGS_DIR.exists() else 0
    return {
        "status": "ok" if existing_roots else "warn",
        "roots": existing_roots,
        "logs": f"{log_count} files" if LOGS_DIR.exists() else "missing",
        "value": f"{len(existing_roots)}/{len(_ARTIFACT_ROOTS)} roots",
        "detail": ", ".join(existing_roots) if existing_roots else "no artifact roots found",
    }


def _genspectra_sidecar_url() -> str:
    host = os.environ.get("SPECTRUMCLAW_GENSPECTRA_HOST", "127.0.0.1")
    port = os.environ.get("SPECTRUMCLAW_GENSPECTRA_PORT", "8231")
    return os.environ.get("SPECTRUMCLAW_GENSPECTRA_URL", f"http://{host}:{port}")


def _is_sensitive_artifact_path(path: Path) -> bool:
    lowered_parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    if any(part.startswith(".") for part in path.parts):
        return True
    if name in {".env", "id_rsa", "id_ed25519"}:
        return True
    return any(token in name for token in ("secret", "token", "credential", "apikey", "api_key"))


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"
