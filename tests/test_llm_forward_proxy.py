from __future__ import annotations

import asyncio
import gzip

import httpx
from starlette.requests import Request

from scripts import llm_forward_proxy


class _BytesStream(httpx.AsyncByteStream):
    def __init__(self, payload: bytes):
        self.payload = payload

    async def __aiter__(self):
        yield self.payload


def test_proxy_preserves_gzip_encoding_for_raw_streams(monkeypatch):
    """Clients must receive both the compressed bytes and their encoding header."""

    payload = gzip.compress(b'data: {"choices": [{"delta": {"content": "ITU"}}]}\n\n')

    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip", "content-type": "text/event-stream"},
            stream=_BytesStream(payload),
        )

    async def forward():
        client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        monkeypatch.setattr(llm_forward_proxy, "_client", client)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "scheme": "http",
                "path": "/v1/chat/completions",
                "raw_path": b"/v1/chat/completions",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "server": ("proxy", 8240),
            },
            receive,
        )
        response = await llm_forward_proxy._forward(request)
        body = b"".join([chunk async for chunk in response.body_iterator])
        await client.aclose()
        return response, body

    response, body = asyncio.run(forward())

    assert response.headers["content-encoding"] == "gzip"
    assert body == payload
    assert gzip.decompress(body).startswith(b"data:")
