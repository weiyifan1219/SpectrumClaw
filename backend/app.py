from __future__ import annotations

import os as _os
_os.environ["LANGCHAIN_TRACING_V2"] = "false"
_os.environ["LANGCHAIN_TRACING"] = "false"
_os.environ["LANGSMITH_TRACING"] = "false"
_os.environ["ANONYMIZED_TELEMETRY"] = "False"

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.chat import router as chat_router
from .api.memory import router as memory_router
from .api.rag import router as rag_router
from .api.spectrum_decision import router as spectrum_decision_router
from .config import get_settings
from .llm.tools import register_default_tools


def create_app() -> FastAPI:
    app = FastAPI(title="SpectrumClaw API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat_router)
    app.include_router(memory_router)
    app.include_router(rag_router)
    app.include_router(spectrum_decision_router)

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

    return app


app = create_app()
