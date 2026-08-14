"""Rate-limiting plugin: per-client fixed-window limiting.

Two backends (see :mod:`prodkit.plugins.rate_limit.backends`):

- ``memory`` (default): per-process counters — correct for a single Uvicorn
  worker or for smoothing bursts, but not a global limit across workers/hosts.
  ``configure()`` logs a warning so this limitation is never silent.
- ``redis``: an aligned fixed window shared across every worker and host
  pointing at the same Redis (``rate_limit={"backend": "redis"}``).

Over-limit requests get a ``429`` RFC 9457 ``problem+json`` response (same shape
as every other framework error) with a ``Retry-After`` header.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from prodkit.contracts.plugin import PRIORITY_RATE_LIMIT, Audit, Check, Plugin
from prodkit.core.context import Context
from prodkit.core.exceptions import ProdKitConfigError
from prodkit.plugins.errors import problem_response
from prodkit.plugins.rate_limit.backends import (
    MemoryBackend,
    RateLimitBackend,
    RedisBackend,
)

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
    """Asks the configured backend whether each request is within its limit."""

    def __init__(self, app, backend: RateLimitBackend):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.backend = backend

    def _client_key(self, request: Request) -> str:
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        key = self._client_key(request)
        decision = await self.backend.hit(key)
        if not decision.allowed:
            logger.warning("Rate limit exceeded for %s on %s", key, request.url.path)
            return problem_response(
                429,
                "Too Many Requests",
                detail="Rate limit exceeded",
                instance=request.url.path,
                headers={"Retry-After": str(decision.retry_after)},
            )
        return await call_next(request)


class RateLimitPlugin(Plugin):
    name: ClassVar[str] = "rate-limit"

    def __init__(self) -> None:
        self._backend: RateLimitBackend | None = None
        self._backend_name = "memory"

    def configure(self, ctx: Context) -> None:
        cfg = ctx.config.rate_limit
        limit, window = parse_rate(cfg.default)
        self._backend_name = cfg.backend
        if cfg.backend == "redis":
            # create_client raises a named ProdKitConfigError if the redis
            # extra is missing; connection itself is verified in startup().
            self._backend = RedisBackend(limit, window, cfg.redis_url, cfg.key_prefix)
        else:
            self._backend = MemoryBackend(limit, window)
            # In-memory = per-process. Say so loudly rather than let ops
            # discover inconsistent limits across workers in production.
            logger.warning(
                "rate-limit: in-memory backend is per-process only; limits are not "
                'shared across workers/hosts. Set rate_limit.backend="redis" for '
                "a shared limit."
            )

    def register_middleware(self, ctx: Context) -> None:
        assert self._backend is not None  # noqa: S101 - configure() runs first
        ctx.add_middleware(
            RateLimitMiddleware, priority=PRIORITY_RATE_LIMIT, backend=self._backend
        )

    async def startup(self, ctx: Context) -> None:
        assert self._backend is not None  # noqa: S101 - configure() runs first
        await self._backend.startup()

    async def shutdown(self, ctx: Context) -> None:
        if self._backend is not None:
            await self._backend.shutdown()

    async def checks(self, ctx: Context) -> list[Check]:
        # Readiness only has something to verify when a shared backend exists.
        if not isinstance(self._backend, RedisBackend):
            return []
        try:
            await self._backend.ping()
        except Exception as exc:
            return [Check(name="rate-limit-redis", passed=False, detail=str(exc))]
        return [Check(name="rate-limit-redis", passed=True, detail="reachable")]

    def doctor(self, ctx: Context) -> list[Audit]:
        cfg = ctx.config.rate_limit
        is_prod = ctx.config.environment == "production"
        if cfg.backend == "redis":
            status, detail, recommendation = "ok", f"{cfg.default} per {cfg.by} (redis)", ""
        elif is_prod:
            status, detail = "warn", f"{cfg.default} per {cfg.by} (in-memory, per-process)"
            recommendation = 'set rate_limit.backend="redis" for a shared, multi-worker limit'
        else:
            status, detail, recommendation = "ok", f"{cfg.default} per {cfg.by} (in-memory)", ""
        return [
            Audit(
                name="Rate limiting",
                status=status,  # type: ignore[arg-type]
                detail=detail,
                recommendation=recommendation,
                weight=10,
            )
        ]
