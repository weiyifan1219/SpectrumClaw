from __future__ import annotations

import os as _os
_os.environ["LANGCHAIN_TRACING_V2"] = "false"
_os.environ["LANGCHAIN_TRACING"] = "false"
_os.environ["LANGSMITH_TRACING"] = "false"
_os.environ["ANONYMIZED_TELEMETRY"] = "False"

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.chat import router as chat_router
from .api.jobs import router as jobs_router
from .api.memory import router as memory_router
from .api.rag import router as rag_router
from .api.spectrum_construction import router as spectrum_construction_router
from .api.spectrum_decision import router as spectrum_decision_router
from .api.uav_spectrum_sim import router as uav_spectrum_sim_router
from .api.uav_agent import router as uav_agent_router
from .api.eval_endpoints import router as eval_router
from .api.frequency_planning import router as frequency_planning_router
from .api.system import router as system_router
from .config import get_settings
from .tools.registry import register_all
from .runtime.resident_state import get_resident_state


def _register_frontend(app: FastAPI) -> None:
    """Serve the production frontend from the same origin as the API."""
    project_root = Path(__file__).resolve().parent.parent
    dist_dir = Path(
        _os.environ.get("SPECTRUMCLAW_FRONTEND_DIST", str(project_root / "frontend" / "dist"))
    ).resolve()

    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    # noVNC supplies the browser-side RFB canvas. The TCP side is never public:
    # it is relayed by /api/uav-spectrum-sim/gui/rfb to loopback-only x11vnc.
    novnc_dir = Path(_os.environ.get("SPECTRUMCLAW_NOVNC_DIR", "/usr/share/novnc"))
    if novnc_dir.is_dir():
        app.mount("/uav-gui", StaticFiles(directory=str(novnc_dir), html=True), name="uav-gui")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend_fallback(path: str):
        """Return static files or index.html for client-side routes."""
        reserved_prefixes = ("api", "health", "docs", "redoc", "openapi.json")
        if any(path == prefix or path.startswith(f"{prefix}/") for prefix in reserved_prefixes):
            raise HTTPException(status_code=404, detail="Not Found")

        index_file = dist_dir / "index.html"
        if not index_file.is_file():
            raise HTTPException(status_code=404, detail="Frontend build not found")

        candidate = (dist_dir / path).resolve()
        try:
            candidate.relative_to(dist_dir)
        except ValueError:
            raise HTTPException(status_code=404, detail="Not Found")

        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_file)


def create_app() -> FastAPI:
    app = FastAPI(title="SpectrumClaw API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat_router)
    app.include_router(jobs_router)
    app.include_router(memory_router)
    app.include_router(rag_router)
    app.include_router(spectrum_construction_router)
    app.include_router(spectrum_decision_router)
    app.include_router(uav_spectrum_sim_router)
    app.include_router(uav_agent_router)
    app.include_router(eval_router)
    app.include_router(frequency_planning_router)
    app.include_router(system_router)

    # register built-in tools
    register_all()

    @app.get("/health")
    async def health() -> dict:
        settings = get_settings()
        provider = settings.provider_profile()
        return {
            "status": "ok",
            "llm": {
                "configured": provider.configured,
                "provider": provider.provider,
                "api_type": provider.api_type,
                "model": provider.model if provider.configured else "",
            },
        }

    @app.on_event("startup")
    async def _warmup():
        """Pre-load resident state so reconnects reuse warm snapshots."""
        try:
            get_resident_state().warmup()
        except Exception:
            pass
        # Pre-load the vector retriever so the first RAG request avoids cold start.
        try:
            from .rag.graph.nodes import _get_vector_retriever
            _get_vector_retriever()
        except Exception:
            pass

    _register_frontend(app)
    return app


app = create_app()
