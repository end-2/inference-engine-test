"""Admission limits also cover the lifetime of streaming responses."""

from fastapi.responses import JSONResponse

from llamacpp.base.server import error_body


class Admission:
    def __init__(self, app, limit):
        self.app, self.limit, self.active = app, limit, 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        if self.active >= self.limit:
            response = JSONResponse(error_body("Request queue is full", "overloaded_error"),
                                    status_code=429, headers={"Retry-After": "1"})
            return await response(scope, receive, send)
        self.active += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.active -= 1
