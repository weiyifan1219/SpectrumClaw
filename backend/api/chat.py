from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..llm.client import chat as llm_chat

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    thinking_enabled: bool = False
    reasoning_effort: str | None = None
    tool_names: list[str] | None = None


class ChatResponse(BaseModel):
    reply: str
    metadata: dict[str, Any]


@router.post("/api/chat", response_model=ChatResponse)
async def handle_chat(request: ChatRequest) -> ChatResponse:
    try:
        reply, metadata = await llm_chat(
            [m.model_dump() for m in request.messages],
            provider_override=request.provider,
            model_override=request.model,
            thinking_enabled=request.thinking_enabled,
            reasoning_effort=request.reasoning_effort,
            tool_names=request.tool_names,
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500].replace("\n", " ").strip()
        detail = f"LLM API returned {exc.response.status_code}"
        if body:
            detail = f"{detail}: {body}"
        raise HTTPException(status_code=502, detail=detail) from exc
    except httpx.HTTPError as exc:
        detail = f"LLM API request failed: {exc.__class__.__name__}"
        message = str(exc).strip()
        if message:
            detail = f"{detail}: {message[:500]}"
        raise HTTPException(status_code=502, detail=detail) from exc
    except ValueError as exc:
        status_code = 400 if str(exc).startswith("Unsupported LLM provider") else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return ChatResponse(reply=reply, metadata=metadata)
