"""Structured logging plugin.

JSON logs in production (machine-parseable), pretty console logs in
development. Every request gets one access-log line with method, path,
status, duration, and the correlated request ID.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any, ClassVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from prodkit.contracts.plugin import PRIORITY_LOGGING, Plugin
from prodkit.core.context import Context
from prodkit.plugins.request_id import get_request_id

_CONTROL_CHARS = dict.fromkeys(range(32))


def _sanitize(value: str) -> str:
    """Strip control characters (CR/LF included) so attacker-controlled
    strings (paths, headers) cannot forge extra log lines."""
    return value.translate(_CONTROL_CHARS)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = get_request_id()
        if request_id:
            entry["request_id"] = request_id
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        extra = getattr(record, "prodkit_extra", None)
        if isinstance(extra, dict):
            entry.update(extra)
        return json.dumps(entry, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        request_id = get_request_id()
        rid = f" [{request_id[:8]}]" if request_id else ""
        base = (
            f"{self.formatTime(record, '%H:%M:%S')} "
            f"{record.levelname:<8}{rid} {record.getMessage()}"
        )
        if record.exc_info and record.exc_info[0] is not None:
            base += "\n" + self.formatException(record.exc_info)
        return base


class AccessLogMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, logger_name: str = "prodkit.access"):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.logger = logging.getLogger(logger_name)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        path = _sanitize(request.url.path)
        self.logger.info(
            "%s %s %d %.1fms",
            request.method,
            path,
            response.status_code,
            duration_ms,
            extra={
                "prodkit_extra": {
                    "method": request.method,
                    "path": path,
                    "status": response.status_code,
                    "duration_ms": round(duration_ms, 1),
                }
            },
        )
        return response


def configure_logging(level: str, log_format: str) -> None:
    formatter: logging.Formatter
    formatter = JSONFormatter() if log_format == "json" else ConsoleFormatter()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    for name in ("prodkit", "prodkit.access"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.setLevel(level.upper())
        logger.propagate = False


class LoggingPlugin(Plugin):
    # No hard dependency on request-id: correlation degrades gracefully to ""
    # when that plugin is disabled, and middleware order comes from priorities.
    name: ClassVar[str] = "logging"

    def configure(self, ctx: Context) -> None:
        cfg = ctx.config.logging
        configure_logging(cfg.level, cfg.format)

    def register_middleware(self, ctx: Context) -> None:
        ctx.add_middleware(AccessLogMiddleware, priority=PRIORITY_LOGGING)
