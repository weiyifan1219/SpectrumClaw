from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.chat import router as chat_router
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
