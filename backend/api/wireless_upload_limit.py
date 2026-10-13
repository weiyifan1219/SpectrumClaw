"""Bound wireless multipart bodies before Starlette spools uploaded files."""
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse


class WirelessUploadLimitMiddleware:
    def __init__(self, app, max_file_bytes: int):
        self.app = app
        # Allow multipart boundaries/headers; the service enforces exact file size.
        self.max_body_bytes = int(max_file_bytes) + 64 * 1024

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('path', '').rstrip('/') != '/api/wireless-recognition/upload':
            return await self.app(scope, receive, send)
        response = JSONResponse({'detail': '上传请求超过大小限制'}, status_code=413)
        for name, value in scope.get('headers', []):
            if name.lower() == b'content-length':
                try:
                    size = int(value)
                except ValueError:
                    return await JSONResponse({'detail': '无效的 Content-Length'}, status_code=400)(scope, receive, send)
                if size > self.max_body_bytes:
                    return await response(scope, receive, send)
        count, exceeded = 0, False

        async def limited_receive():
            nonlocal count, exceeded
            message = await receive()
            if message['type'] == 'http.request':
                count += len(message.get('body', b''))
                if count > self.max_body_bytes:
                    exceeded = True
                    # Multipart parser catches this type and closes spooled files.
                    raise MultiPartException('wireless upload body too large')
            return message

        async def limited_send(message):
            if exceeded:
                if message['type'] == 'http.response.start':
                    await response(scope, receive, send)
                return
            await send(message)

        await self.app(scope, limited_receive, limited_send)
