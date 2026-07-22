"""Rate-limiting plugin: per-client fixed-window limiting, in-memory backend.

The in-memory backend counts requests per client IP in a fixed time window. It
is **per-process** — correct for a single Uvicorn worker or for smoothing bursts
behind a load balancer, but not a global limit across workers/hosts. A Redis
backend for a shared, multi-worker limit lands in v0.3; ``configure()`` logs a
warning so this limitation is never silent.

Over-limit requests get a ``429`` RFC 9457 ``problem+json`` response (same shape
as every other framework error) with a ``Retry-After`` header.
"""

from __future__ import annotations

import logging
import time
from typing import ClassVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from prodkit.contracts.plugin import PRIORITY_RATE_LIMIT, Audit, Plugin
from prodkit.core.context import Context
from prodkit.core.exceptions import ProdKitConfigError
from prodkit.plugins.errors import problem_response

logger = logging.getLogger("prodkit")

_UNITS: dict[str, int] = {
    "second": 1,
    "sec": 1,
    "s": 1,
    "minute": 60,
    "min": 60,
    "m": 60,
    "hour": 3600,
    "hr": 3600,
    "h": 3600,
}


def parse_rate(spec: str) -> tuple[int, int]:
    """Parse ``"100/minute"`` → ``(100, 60)`` (limit, window in seconds).

    Raises :class:`ProdKitConfigError` (naming ``rate_limit.default``) on a
    malformed spec so misconfiguration fails at boot, not at request time.
    """
    raw = spec.replace(" ", "")
    if "/" not in raw:
        raise ProdKitConfigError(
            f"rate_limit.default: {spec!r} must look like '100/minute' (count/period)"
        )
    count_str, _, unit = raw.partition("/")
    try:
        count = int(count_str)
    except ValueError:
        raise ProdKitConfigError(
            f"rate_limit.default: {count_str!r} in {spec!r} is not an integer count"
        ) from None
    if count <= 0:
        raise ProdKitConfigError(f"rate_limit.default: count in {spec!r} must be positive")
    window = _UNITS.get(unit.lower())
    if window is None:
        raise ProdKitConfigError(
            f"rate_limit.default: unknown period {unit!r} in {spec!r}; use second, minute, or hour"
        )
    return count, window


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window counter keyed on client IP.

    State is a single dict mutated only on the event loop (no ``await`` between
    read and increment), so it needs no lock within a single process.
    """

    def __init__(self, app, limit: int, window: int):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.limit = limit
        self.window = window
        # ip -> (window_start_monotonic, count_in_window)
        self._buckets: dict[str, tuple[float, int]] = {}

    def _client_key(self, request: Request) -> str:
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        now = time.monotonic()
        key = self._client_key(request)
        start, count = self._buckets.get(key, (now, 0))
        if now - start >= self.window:
            # Window elapsed: reset.
            start, count = now, 0

        if count >= self.limit:
            retry_after = max(1, int(self.window - (now - start)))
            logger.warning("Rate limit exceeded for %s on %s", key, request.url.path)
            return problem_response(
                429,
                "Too Many Requests",
                detail=f"Rate limit of {self.limit} per {self.window}s exceeded",
                instance=request.url.path,
                headers={"Retry-After": str(retry_after)},
            )

        self._buckets[key] = (start, count + 1)
        return await call_next(request)


class RateLimitPlugin(Plugin):
    name: ClassVar[str] = "rate-limit"

    def __init__(self) -> None:
        self._limit = 0
        self._window = 0

    def configure(self, ctx: Context) -> None:
        self._limit, self._window = parse_rate(ctx.config.rate_limit.default)
        # In-memory = per-process. Say so loudly rather than let ops discover
        # inconsistent limits across workers in production.
        logger.warning(
            "rate-limit: in-memory backend is per-process only; limits are not "
            "shared across workers/hosts. A shared Redis backend arrives in v0.3."
        )

    def register_middleware(self, ctx: Context) -> None:
        ctx.add_middleware(
            RateLimitMiddleware,
            priority=PRIORITY_RATE_LIMIT,
            limit=self._limit,
            window=self._window,
        )

    def doctor(self, ctx: Context) -> list[Audit]:
        cfg = ctx.config.rate_limit
        return [
            Audit(
                name="Rate limiting",
                status="ok" if cfg.enabled else "warn",
                detail=f"{cfg.default} per {cfg.by}" if cfg.enabled else "disabled",
                recommendation=(
                    "" if cfg.enabled else "enable for public APIs to blunt abuse and brute-force"
                ),
                weight=10,
            )
        ]
