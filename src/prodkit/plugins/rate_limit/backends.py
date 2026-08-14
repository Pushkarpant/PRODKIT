"""Rate-limit backends: where the counting happens.

``MemoryBackend`` keeps the v0.2 semantics: a per-process fixed window keyed on
client IP. ``RedisBackend`` shares an aligned fixed window across every worker
and host that points at the same Redis.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger("prodkit")


@dataclass
class RateDecision:
    """The backend's verdict for one request."""

    allowed: bool
    retry_after: int = 0  # seconds; meaningful when not allowed


class RateLimitBackend(Protocol):
    """Contract shared by the memory and Redis backends."""

    async def hit(self, key: str) -> RateDecision: ...

    async def startup(self) -> None: ...

    async def shutdown(self) -> None: ...


class MemoryBackend:
    """Fixed-window counter in a per-process dict.

    State is mutated only on the event loop with no ``await`` between read and
    increment, so it needs no lock within a single process.
    """

    def __init__(self, limit: int, window: int) -> None:
        self.limit = limit
        self.window = window
        # key -> (window_start_monotonic, count_in_window)
        self._buckets: dict[str, tuple[float, int]] = {}

    async def hit(self, key: str) -> RateDecision:
        now = time.monotonic()
        start, count = self._buckets.get(key, (now, 0))
        if now - start >= self.window:
            # Window elapsed: reset.
            start, count = now, 0
        if count >= self.limit:
            return RateDecision(
                allowed=False, retry_after=max(1, int(self.window - (now - start)))
            )
        self._buckets[key] = (start, count + 1)
        return RateDecision(allowed=True)

    async def startup(self) -> None:
        """Nothing to acquire."""

    async def shutdown(self) -> None:
        """Nothing to release."""


class RedisBackend:
    """Aligned fixed window shared across workers/hosts via Redis.

    The window index is part of the key (``prefix + key + ":" + epoch//window``),
    so windows partition themselves; one pipeline does ``SET key 0 EX window+1 NX``
    (guarantees a TTL no matter which worker creates the key) followed by an
    atomic ``INCR``. **Fails open**: if Redis errors at request time the request
    is allowed and a warning logged — availability beats strict limiting.
    """

    def __init__(self, limit: int, window: int, url: str, prefix: str) -> None:
        self.limit = limit
        self.window = window
        self.prefix = prefix
        from prodkit.plugins._redis import create_client

        self._client: Redis = create_client(url, section="rate_limit")

    async def hit(self, key: str) -> RateDecision:
        now = time.time()
        window_key = f"{self.prefix}{key}:{int(now // self.window)}"
        try:
            pipe = self._client.pipeline(transaction=False)
            pipe.set(window_key, 0, ex=self.window + 1, nx=True)
            pipe.incr(window_key)
            _, count = await pipe.execute()
        except Exception:
            logger.warning(
                "rate-limit: Redis unavailable; failing open (request allowed)", exc_info=True
            )
            return RateDecision(allowed=True)
        if int(count) > self.limit:
            return RateDecision(
                allowed=False, retry_after=max(1, self.window - int(now % self.window))
            )
        return RateDecision(allowed=True)

    async def startup(self) -> None:
        # Fail fast at boot if Redis is unreachable, not on the first request.
        await self.ping()

    async def ping(self) -> None:
        await self._client.ping()

    async def shutdown(self) -> None:
        await self._client.aclose()
