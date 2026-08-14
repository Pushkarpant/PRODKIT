"""Cache plugin: a named cache service other plugins and user code can share.

The service is published in the registry under ``"cache"``::

    cache = ctx.registry.get("cache")
    await cache.set("user:42", {"name": "Ada"}, ttl=60)
    user = await cache.get("user:42")

Two backends: ``memory`` (per-process LRU with TTL, the default) and ``redis``
(shared across workers/hosts). Values must be JSON-serializable so behavior is
identical across backends.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from prodkit.contracts.plugin import Audit, Check, Plugin
from prodkit.core.context import Context

if TYPE_CHECKING:
    from redis.asyncio import Redis


class CacheService(Protocol):
    """The contract of the registry's ``"cache"`` service.

    ``ttl=None`` means the configured default TTL; ``ttl=0`` means no expiry.
    """

    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...


class MemoryCache:
    """Per-process LRU cache with monotonic-deadline TTLs (lazy expiry)."""

    def __init__(self, default_ttl: int, max_entries: int) -> None:
        self.default_ttl = default_ttl
        self.max_entries = max_entries
        # key -> (deadline_monotonic | None, value); insertion order = LRU order
        self._data: OrderedDict[str, tuple[float | None, Any]] = OrderedDict()

    def _deadline(self, ttl: int | None) -> float | None:
        effective = self.default_ttl if ttl is None else ttl
        return None if effective == 0 else time.monotonic() + effective

    async def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        deadline, value = item
        if deadline is not None and time.monotonic() >= deadline:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._data[key] = (self._deadline(ttl), value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)  # evict least recently used

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


class RedisCache:
    """Redis-backed cache; values JSON-encoded, keys prefixed."""

    def __init__(self, url: str, default_ttl: int, prefix: str) -> None:
        self.default_ttl = default_ttl
        self.prefix = prefix
        from prodkit.plugins._redis import create_client

        self._client: Redis = create_client(url, section="cache")

    async def get(self, key: str) -> Any | None:
        raw = await self._client.get(self.prefix + key)
        return None if raw is None else json.loads(raw)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        effective = self.default_ttl if ttl is None else ttl
        await self._client.set(
            self.prefix + key,
            json.dumps(value),
            ex=effective if effective > 0 else None,
        )

    async def delete(self, key: str) -> None:
        await self._client.delete(self.prefix + key)

    async def ping(self) -> None:
        await self._client.ping()

    async def aclose(self) -> None:
        await self._client.aclose()


class CachePlugin(Plugin):
    name: ClassVar[str] = "cache"

    def __init__(self) -> None:
        self._cache: CacheService | None = None

    def configure(self, ctx: Context) -> None:
        cfg = ctx.config.cache
        if cfg.backend == "redis":
            # create_client raises a named ProdKitConfigError if the redis
            # extra is missing; connection itself is verified in startup().
            self._cache = RedisCache(cfg.redis_url, cfg.default_ttl, cfg.key_prefix)
        else:
            self._cache = MemoryCache(cfg.default_ttl, cfg.max_entries)
        ctx.registry.provide("cache", self._cache)

    async def startup(self, ctx: Context) -> None:
        if isinstance(self._cache, RedisCache):
            # Fail fast at boot if Redis is unreachable.
            await self._cache.ping()

    async def shutdown(self, ctx: Context) -> None:
        if isinstance(self._cache, RedisCache):
            await self._cache.aclose()

    async def checks(self, ctx: Context) -> list[Check]:
        if not isinstance(self._cache, RedisCache):
            return []
        try:
            await self._cache.ping()
        except Exception as exc:
            return [Check(name="cache-redis", passed=False, detail=str(exc))]
        return [Check(name="cache-redis", passed=True, detail="reachable")]

    def doctor(self, ctx: Context) -> list[Audit]:
        cfg = ctx.config.cache
        return [
            Audit(
                name="Cache",
                status="ok",
                detail=f"{cfg.backend} backend, default_ttl={cfg.default_ttl}s",
                weight=5,
            )
        ]
