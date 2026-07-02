from __future__ import annotations

import json as _json
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..agent.run_events import error as run_error
from ..agent.run_events import standardize_event
from ..llm.client import chat as llm_chat
from ..llm.model_registry import llm_options_payload
from ..agent.runtime import stream_chat as runtime_stream_chat
from ..runtime.jobs import get_job_store
from ..runtime.resident_state import get_resident_state

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
    thread_id: str = ""


class ChatResponse(BaseModel):
    reply: str
    metadata: dict[str, Any]


@router.get("/api/llm/options")
async def handle_llm_options() -> dict[str, Any]:
    return llm_options_payload(get_settings())


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


@router.post("/api/chat/stream")
async def handle_chat_stream(request: ChatRequest):
    prompt_preview = _latest_user_content(request.messages)
    job_id = get_job_store().start_job(
        kind="chat",
        title=f"Chat · {prompt_preview[:48] or 'stream'}",
        thread_id=request.thread_id,
        provider=request.provider or "",
        model=request.model or "",
        prompt_preview=prompt_preview[:160],
    )

    async def generate():
        try:
            async for event in runtime_stream_chat(
                [m.model_dump() for m in request.messages],
                provider_override=request.provider,
                model_override=request.model,
                thinking_enabled=request.thinking_enabled,
                reasoning_effort=request.reasoning_effort,
                tool_names=request.tool_names,
                thread_id=request.thread_id,
            ):
                event = standardize_event(event, source="chat")
                event = get_job_store().record_event(job_id, event)
                yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            event = get_job_store().record_event(job_id, run_error(str(exc), source="chat"))
            yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/api/kb/stats")
async def handle_kb_stats():
    """Return resident knowledge base statistics for long-lived UI panels."""
    return get_resident_state().kb_stats()


def _latest_user_content(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user" and message.content.strip():
            return message.content.strip()
    return ""
