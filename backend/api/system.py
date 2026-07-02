"""Read-only endpoints for logs and output artifacts.

Intentionally minimal — list + tail logs, browse + preview + download artifacts.
Does not mutate anything; safe to use while mineru / RAG pipelines are running.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ..config import get_settings
from ..runtime.resident_state import (
    LOGS_DIR,
    PROJECT_ROOT,
    format_bytes,
    get_resident_state,
    guess_media_type,
    rel_path,
    resolve_artifact_path,
)

router = APIRouter()


# ── Logs ──────────────────────────────────────────────────────────────

@router.get("/api/system/logs")
async def list_logs():
    """List available log files in logs/ with metadata."""
    return {"logs": get_resident_state().list_logs()}


@router.get("/api/system/logs/{name}")
async def get_log(
    name: str,
    tail: int = Query(100, ge=1, le=5000, description="Return last N lines"),
    download: bool = Query(False, description="Download as text file"),
):
    """Fetch log file content, defaulting to the last `tail` lines."""
    path = LOGS_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Log not found: {name}")

    if download:
        return FileResponse(
            path, media_type="text/plain; charset=utf-8",
            filename=name,
        )

    try:
        return get_resident_state().get_log(name, tail=tail)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Log not found: {name}") from exc


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
        _check("Runtime", "Project Root", "ok" if PROJECT_ROOT.exists() else "error", rel_path(PROJECT_ROOT), "workspace"),
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
        _check("Service", "Logs", "ok" if LOGS_DIR.exists() else "warn", artifacts["logs"], rel_path(LOGS_DIR)),
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
    items = get_resident_state().list_artifacts(category=category, search=search, limit=limit)
    return {"artifacts": items}


@router.get("/api/system/artifacts/preview/{filepath:path}")
async def preview_artifact(filepath: str):
    """Return text content of a previewable artifact."""
    try:
        return get_resident_state().artifact_preview(filepath)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"File not found: {filepath}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/system/artifacts/download/{filepath:path}")
async def download_artifact(
    filepath: str,
    inline: bool = Query(False, description="Serve inline (preview) instead of download"),
):
    """Download or inline-view any artifact file."""
    path = resolve_artifact_path(filepath)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {filepath}")
    kwargs: dict = {"media_type": guess_media_type(path)}
    if not inline:
        kwargs["filename"] = path.name  # triggers Content-Disposition: attachment
    return FileResponse(path, **kwargs)


# ── helpers ───────────────────────────────────────────────────────────


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
    path_value = rel_path(path)
    if not path.exists():
        return {
            "status": "warn",
            "path": path_value,
            "exists": False,
            "size": 0,
            "value": "未创建",
            "detail": path_value,
        }
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1) as conn:
            conn.execute("select 1").fetchone()
    except sqlite3.Error as exc:
        return {
            "status": "error",
            "path": path_value,
            "exists": True,
            "size": path.stat().st_size,
            "value": "不可读",
            "detail": exc.__class__.__name__,
        }
    return {
        "status": "ok",
        "path": path_value,
        "exists": True,
        "size": path.stat().st_size,
        "value": format_bytes(path.stat().st_size),
        "detail": path_value,
    }


def _rag_health() -> dict[str, Any]:
    return get_resident_state().rag_health()


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
    return get_resident_state().artifact_health()


def _genspectra_sidecar_url() -> str:
    host = os.environ.get("SPECTRUMCLAW_GENSPECTRA_HOST", "127.0.0.1")
    port = os.environ.get("SPECTRUMCLAW_GENSPECTRA_PORT", "8231")
    return os.environ.get("SPECTRUMCLAW_GENSPECTRA_URL", f"http://{host}:{port}")
