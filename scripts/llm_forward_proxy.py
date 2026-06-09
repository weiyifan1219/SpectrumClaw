"""Local LLM forward proxy for offline 3090 server.

The 3090 server has no internet. This proxy runs on the local machine (which
can reach api.deepseek.com), and is exposed to the server via an SSH reverse
tunnel (ssh -R 8240:127.0.0.1:8240). The server points
DEEPSEEK_BASE_URL=http://127.0.0.1:8240/v1 at this proxy.

It transparently forwards any path to UPSTREAM, preserving method, body, and
the Authorization header, and streams the response back (SSE-friendly).

Run:
    python scripts/llm_forward_proxy.py            # default 127.0.0.1:8240 -> api.deepseek.com
    UPSTREAM=https://api.deepseek.com PORT=8240 python scripts/llm_forward_proxy.py
"""

from __future__ import annotations

import os

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

UPSTREAM = os.environ.get("UPSTREAM", "https://api.deepseek.com").rstrip("/")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8240"))
TIMEOUT = float(os.environ.get("PROXY_TIMEOUT", "300"))

# Headers we must not blindly forward (hop-by-hop / host-specific).
_DROP_REQ = {"host", "content-length", "connection", "accept-encoding"}
_DROP_RESP = {"content-encoding", "transfer-encoding", "connection", "content-length"}

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT))
    return _client


async def _forward(request: Request) -> Response:
    path = request.url.path
    query = request.url.query
    target = f"{UPSTREAM}{path}"
    if query:
        target = f"{target}?{query}"

    fwd_headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQ
    }
    body = await request.body()

    client = _get_client()
    upstream_req = client.build_request(
        request.method, target, headers=fwd_headers, content=body
    )
    upstream_resp = await client.send(upstream_req, stream=True)

    resp_headers = {
        k: v for k, v in upstream_resp.headers.items() if k.lower() not in _DROP_RESP
    }

    async def _body_iter():
        try:
            async for chunk in upstream_resp.aiter_raw():
                yield chunk
        finally:
            await upstream_resp.aclose()

    return StreamingResponse(
        _body_iter(),
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        media_type=upstream_resp.headers.get("content-type"),
    )


async def _health(request: Request) -> Response:
    return Response(f"ok -> {UPSTREAM}", media_type="text/plain")


app = Starlette(
    routes=[
        Route("/_proxy_health", _health, methods=["GET"]),
        Route("/{path:path}", _forward, methods=["GET", "POST", "PUT", "DELETE", "PATCH"]),
    ]
)


if __name__ == "__main__":
    print(f"[llm_forward_proxy] {HOST}:{PORT} -> {UPSTREAM} (timeout={TIMEOUT}s)")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
