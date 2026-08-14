"""Unit + integration tests for the rate-limiting plugin and its backends."""

from __future__ import annotations

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prodkit import Production
from prodkit.core.exceptions import ProdKitConfigError
from prodkit.plugins.rate_limit import parse_rate
from prodkit.plugins.rate_limit.backends import RedisBackend
from tests.conftest import NO_TOML


class TestParseRate:
    @pytest.mark.parametrize(
        "spec,expected",
        [
            ("100/minute", (100, 60)),
            ("10/second", (10, 1)),
            ("5/hour", (5, 3600)),
            ("30 / min", (30, 60)),
            ("2/h", (2, 3600)),
        ],
    )
    def test_valid(self, spec, expected):
        assert parse_rate(spec) == expected

    @pytest.mark.parametrize("spec", ["100", "abc/minute", "10/fortnight", "0/minute", "-3/hour"])
    def test_invalid_raises_named_error(self, spec):
        with pytest.raises(ProdKitConfigError, match=r"rate_limit\.default"):
            parse_rate(spec)


def build_app(**rate_limit) -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    Production(
        app,
        config_file=NO_TOML,
        environment="production",
        rate_limit={"default": "3/minute", **rate_limit},
    )
    return app


@pytest.fixture
def fake_redis(monkeypatch):
    """Route every plugin Redis client to one shared fakeredis server."""
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        "prodkit.plugins._redis.create_client",
        lambda url, section="redis": fakeredis.aioredis.FakeRedis(server=server),
    )
    return server


class TestMemoryBackendMiddleware:
    def test_allows_up_to_limit_then_429(self):
        with TestClient(build_app()) as client:
            for _ in range(3):
                assert client.get("/ping").status_code == 200
            resp = client.get("/ping")
            assert resp.status_code == 429
            assert resp.headers["content-type"].startswith("application/problem+json")
            assert "retry-after" in {k.lower() for k in resp.headers}
            body = resp.json()
            assert body["title"] == "Too Many Requests"
            assert body["status"] == 429
            assert body["instance"] == "/ping"

    def test_window_resets_after_elapse(self, monkeypatch):
        import prodkit.plugins.rate_limit.backends as backends

        fake = {"t": 1000.0}
        monkeypatch.setattr(backends.time, "monotonic", lambda: fake["t"])
        with TestClient(build_app()) as client:
            for _ in range(3):
                assert client.get("/ping").status_code == 200
            assert client.get("/ping").status_code == 429
            fake["t"] += 61  # advance past the 60s window
            assert client.get("/ping").status_code == 200

    def test_disabled_by_default(self):
        app = FastAPI()

        @app.get("/ping")
        def ping():
            return {"ok": True}

        prod = Production(app, config_file=NO_TOML, environment="production")
        assert "rate-limit" not in {p.name for p in prod.plugins}
        with TestClient(app) as client:
            for _ in range(10):
                assert client.get("/ping").status_code == 200

    def test_bad_spec_fails_at_boot(self):
        with pytest.raises(ProdKitConfigError, match=r"rate_limit\.default"):
            Production(
                FastAPI(),
                config_file=NO_TOML,
                environment="production",
                rate_limit={"default": "not-a-rate"},
            )


class TestRedisBackend:
    def test_allows_up_to_limit_then_429(self, fake_redis):
        with TestClient(build_app(backend="redis")) as client:
            for _ in range(3):
                assert client.get("/ping").status_code == 200
            resp = client.get("/ping")
            assert resp.status_code == 429
            assert int(resp.headers["retry-after"]) >= 1

    @pytest.mark.anyio
    async def test_counter_key_always_has_ttl(self, fake_redis):
        backend = RedisBackend(limit=5, window=60, url="redis://x", prefix="t:")
        await backend.hit("1.2.3.4")
        keys = [k async for k in backend._client.scan_iter("t:*")]
        assert len(keys) == 1
        assert await backend._client.ttl(keys[0]) > 0
        await backend.shutdown()

    @pytest.mark.anyio
    async def test_window_rollover(self, fake_redis, monkeypatch):
        import prodkit.plugins.rate_limit.backends as backends

        fake_t = {"t": 1000.0}
        monkeypatch.setattr(backends.time, "time", lambda: fake_t["t"])
        backend = RedisBackend(limit=1, window=60, url="redis://x", prefix="t:")
        assert (await backend.hit("ip")).allowed
        assert not (await backend.hit("ip")).allowed
        fake_t["t"] += 60  # next aligned window -> new key
        assert (await backend.hit("ip")).allowed
        await backend.shutdown()

    @pytest.mark.anyio
    async def test_fails_open_when_redis_errors(self, fake_redis):
        backend = RedisBackend(limit=1, window=60, url="redis://x", prefix="t:")

        class Boom:
            def pipeline(self, transaction=False):
                raise ConnectionError("redis down")

        backend._client = Boom()
        decision = await backend.hit("ip")
        assert decision.allowed  # availability beats strict limiting

    def test_missing_redis_dep_fails_with_pip_hint(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def no_redis(name, *args, **kwargs):
            if name.startswith("redis"):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_redis)
        with pytest.raises(ProdKitConfigError, match=r"prodkit\[redis\]"):
            build_app(backend="redis")

    def test_startup_ping_failure_fails_boot(self, monkeypatch):
        class DeadRedis(fakeredis.aioredis.FakeRedis):
            async def ping(self):
                raise ConnectionError("unreachable")

        monkeypatch.setattr(
            "prodkit.plugins._redis.create_client",
            lambda url, section="redis": DeadRedis(),
        )
        with (
            pytest.raises(ConnectionError, match="unreachable"),
            TestClient(build_app(backend="redis")),
        ):
            pass

    def test_ready_reflects_redis_reachability(self, fake_redis):
        with TestClient(build_app(backend="redis")) as client:
            body = client.get("/ready").json()
            checks = {c["name"]: c for c in body["checks"]}
            assert checks["rate-limit-redis"]["passed"] is True


class TestDoctorAudit:
    def test_memory_backend_warns_in_production(self):
        prod = Production(
            FastAPI(),
            config_file=NO_TOML,
            environment="production",
            rate_limit={"default": "3/minute"},
        )
        plugin = next(p for p in prod.plugins if p.name == "rate-limit")
        (audit,) = plugin.doctor(prod.context)
        assert audit.status == "warn"
        assert "redis" in audit.recommendation

    def test_redis_backend_is_ok(self, fake_redis):
        prod = Production(
            FastAPI(),
            config_file=NO_TOML,
            environment="production",
            rate_limit={"default": "3/minute", "backend": "redis"},
        )
        plugin = next(p for p in prod.plugins if p.name == "rate-limit")
        (audit,) = plugin.doctor(prod.context)
        assert audit.status == "ok"
        assert "redis" in audit.detail
