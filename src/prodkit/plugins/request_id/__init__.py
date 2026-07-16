"""Request-ID plugin: generates/propagates X-Request-ID and exposes it via a
contextvar so the logging plugin can correlate every log line to a request."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar
from typing import ClassVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from prodkit.contracts.plugin import PRIORITY_REQUEST_ID, Plugin
from prodkit.core.context import Context

request_id_var: ContextVar[str] = ContextVar("prodkit_request_id", default="")

# Inbound IDs are attacker-controlled input headed for logs and response
# headers: constrain to a safe charset and length to prevent log injection.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def get_request_id() -> str:
    """The current request's ID, or '' outside a request."""
    return request_id_var.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, header: str = "X-Request-ID", trust_incoming: bool = False):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.header = header
        self.trust_incoming = trust_incoming

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(self.header, "")
        if self.trust_incoming and incoming and _SAFE_ID.match(incoming):
            request_id = incoming
        else:
            request_id = uuid.uuid4().hex
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[self.header] = request_id
        return response


class RequestIDPlugin(Plugin):
    name: ClassVar[str] = "request-id"

    def register_middleware(self, ctx: Context) -> None:
        cfg = ctx.config.request_id
        ctx.add_middleware(
            RequestIDMiddleware,
            priority=PRIORITY_REQUEST_ID,
            header=cfg.header,
            trust_incoming=cfg.trust_incoming,
        )
