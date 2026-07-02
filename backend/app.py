from __future__ import annotations

import os as _os
_os.environ["LANGCHAIN_TRACING_V2"] = "false"
_os.environ["LANGCHAIN_TRACING"] = "false"
_os.environ["LANGSMITH_TRACING"] = "false"
_os.environ["ANONYMIZED_TELEMETRY"] = "False"

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.chat import router as chat_router
from .api.jobs import router as jobs_router
from .api.memory import router as memory_router
from .api.rag import router as rag_router
from .api.spectrum_construction import router as spectrum_construction_router
from .api.spectrum_decision import router as spectrum_decision_router
from .api.eval_endpoints import router as eval_router
from .api.system import router as system_router
from .config import get_settings
from .llm.tools import register_default_tools
from .runtime.resident_state import get_resident_state


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
    app.include_router(eval_router)
    app.include_router(system_router)

    # register built-in tools
    register_default_tools()

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

    return app


app = create_app()
