"""Read-only endpoints for logs and output artifacts.

Intentionally minimal — list + tail logs, browse + preview + download artifacts.
Does not mutate anything; safe to use while mineru / RAG pipelines are running.
"""

from __future__ import annotations

import os
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # SpectrumClaw/
LOGS_DIR = PROJECT_ROOT / "logs"
DATA_DIR = PROJECT_ROOT / "data"

PREVIEWABLE_TEXT_EXTS = {
    ".md", ".txt", ".log", ".json", ".yaml", ".yml",
    ".csv", ".xml", ".html", ".py", ".sh", ".cfg", ".ini",
    ".toml", ".env", ".css", ".js", ".ts", ".jsx", ".tsx",
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
    """Resolve a relative path under PROJECT_ROOT; reject escapes."""
    candidate = (PROJECT_ROOT / relative).resolve()
    try:
        candidate.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return None
    return candidate


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
