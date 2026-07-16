"""Errors plugin: normalized error responses per RFC 9457 (problem+json).

- HTTPException and validation errors keep their semantics, reshaped into a
  consistent problem-details body (via FastAPI exception handlers).
- Unhandled exceptions are caught by our own middleware INSIDE the request-id
  scope — Starlette's outermost ServerErrorMiddleware would run after the
  request-id contextvar is reset, losing log/response correlation. The
  traceback is logged with the request ID, never sent to the client (unless
  include_debug_details, which the config layer refuses in production).
"""

from __future__ import annotations

import logging
import traceback
from typing import Any, ClassVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from prodkit.contracts.plugin import PRIORITY_ERRORS, Plugin
from prodkit.core.context import Context
from prodkit.plugins.request_id import get_request_id

logger = logging.getLogger("prodkit")

_MEDIA_TYPE = "application/problem+json"


def _problem(status: int, title: str, detail: Any = None, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    request_id = get_request_id()
    if request_id:
        body["request_id"] = request_id
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type=_MEDIA_TYPE)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Catch-all for exceptions no handler dealt with. Runs inside request-id
    and logging middleware so the 500 is correlated and access-logged."""

    def __init__(self, app, include_debug_details: bool = False):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.include_debug_details = include_debug_details

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            # Full traceback to logs (correlated by request ID) ...
            logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
            if self.include_debug_details:
                return _problem(
                    500,
                    "Internal Server Error",
                    detail=str(exc),
                    traceback=traceback.format_exc().splitlines(),
                )
            # ... opaque response to the client. The request_id in the body
            # is what support/ops use to find the logged traceback.
            return _problem(500, "Internal Server Error")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        response = _problem(exc.status_code, exc.detail or "HTTP error")
        for key, value in (exc.headers or {}).items():
            response.headers[key] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _problem(422, "Validation error", detail=exc.errors())


class ErrorsPlugin(Plugin):
    name: ClassVar[str] = "errors"

    def register_middleware(self, ctx: Context) -> None:
        ctx.add_middleware(
            ErrorHandlingMiddleware,
            priority=PRIORITY_ERRORS,
            include_debug_details=ctx.config.errors.include_debug_details,
        )

    def register_routes(self, ctx: Context) -> None:
        install_error_handlers(ctx.app)
