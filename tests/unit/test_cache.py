"""Unit tests for the cache plugin: memory and Redis backends, registry wiring."""

from __future__ import annotations

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prodkit import Production
from prodkit.core.exceptions import ProdKitConfigError
from prodkit.plugins.cache import MemoryCache, RedisCache
from tests.conftest import NO_TOML


@pytest.fixture
def fake_redis(monkeypatch):
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        "prodkit.plugins._redis.create_client",
        lambda url, section="redis": fakeredis.aioredis.FakeRedis(server=server),
    )
    return server


def build_prod(**cache) -> Production:
    return Production(
        FastAPI(),
        config_file=NO_TOML,
        environment="production",
        cache={**cache},
    )


class TestMemoryCache:
    @pytest.mark.anyio
    async def test_set_get_delete_roundtrip(self):
        cache = MemoryCache(default_ttl=300, max_entries=10)
        await cache.set("k", {"a": 1})
        assert await cache.get("k") == {"a": 1}
        await cache.delete("k")
        assert await cache.get("k") is None

    @pytest.mark.anyio
    async def test_ttl_expiry(self, monkeypatch):
        import prodkit.plugins.cache as cache_mod

        fake = {"t": 1000.0}
        monkeypatch.setattr(cache_mod.time, "monotonic", lambda: fake["t"])
        cache = MemoryCache(default_ttl=300, max_entries=10)
        await cache.set("k", "v", ttl=60)
        assert await cache.get("k") == "v"
        fake["t"] += 61
        assert await cache.get("k") is None

    @pytest.mark.anyio
    async def test_ttl_zero_means_no_expiry(self, monkeypatch):
        import prodkit.plugins.cache as cache_mod

        fake = {"t": 1000.0}
        monkeypatch.setattr(cache_mod.time, "monotonic", lambda: fake["t"])
        cache = MemoryCache(default_ttl=300, max_entries=10)
        await cache.set("k", "v", ttl=0)
        fake["t"] += 10_000_000
        assert await cache.get("k") == "v"

    @pytest.mark.anyio
    async def test_lru_eviction_at_max_entries(self):
        cache = MemoryCache(default_ttl=0, max_entries=2)
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.get("a")  # touch: 'a' becomes most recently used
        await cache.set("c", 3)  # evicts 'b', the least recently used
        assert await cache.get("a") == 1
        assert await cache.get("b") is None
        assert await cache.get("c") == 3


class TestRedisCache:
    @pytest.mark.anyio
    async def test_json_roundtrip_with_prefix(self, fake_redis):
        cache = RedisCache("redis://x", default_ttl=300, prefix="app:")
        await cache.set("user", {"name": "Ada", "n": 7})
        assert await cache.get("user") == {"name": "Ada", "n": 7}
        # the raw key in redis carries the prefix
        assert await cache._client.exists("app:user")
        await cache.delete("user")
        assert await cache.get("user") is None
        await cache.aclose()

    @pytest.mark.anyio
    async def test_ttl_applied(self, fake_redis):
        cache = RedisCache("redis://x", default_ttl=300, prefix="app:")
        await cache.set("k", "v", ttl=60)
        assert 0 < await cache._client.ttl("app:k") <= 60
        await cache.set("forever", "v", ttl=0)
        assert await cache._client.ttl("app:forever") == -1  # no expiry
        await cache.aclose()


class TestCachePlugin:
    def test_registry_provides_cache_service(self):
        prod = build_prod()
        assert prod.context.registry.has("cache")
        assert isinstance(prod.context.registry.get("cache"), MemoryCache)

    def test_disabled_by_default(self):
        prod = Production(FastAPI(), config_file=NO_TOML, environment="production")
        assert "cache" not in {p.name for p in prod.plugins}

    def test_redis_backend_readiness_check(self, fake_redis):
        app = FastAPI()
        Production(
            app,
            config_file=NO_TOML,
            environment="production",
            cache={"backend": "redis"},
        )
        with TestClient(app) as client:
            body = client.get("/ready").json()
            checks = {c["name"]: c for c in body["checks"]}
            assert checks["cache-redis"]["passed"] is True

    def test_memory_backend_has_no_readiness_check(self):
        app = FastAPI()
        Production(app, config_file=NO_TOML, environment="production", cache=True)
        with TestClient(app) as client:
            names = {c["name"] for c in client.get("/ready").json()["checks"]}
            assert "cache-redis" not in names

    def test_doctor_audit(self):
        prod = build_prod()
        plugin = next(p for p in prod.plugins if p.name == "cache")
        (audit,) = plugin.doctor(prod.context)
        assert audit.status == "ok"
        assert "memory" in audit.detail

    def test_missing_redis_dep_fails_with_pip_hint(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def no_redis(name, *args, **kwargs):
            if name.startswith("redis"):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_redis)
        with pytest.raises(ProdKitConfigError, match=r"prodkit\[redis\]"):
            build_prod(backend="redis")
