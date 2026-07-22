"""Unit + integration tests for the rate-limiting plugin."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prodkit import Production
from prodkit.core.exceptions import ProdKitConfigError
from prodkit.plugins.rate_limit import parse_rate
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


class TestRateLimitMiddleware:
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
        import prodkit.plugins.rate_limit as rl

        fake = {"t": 1000.0}
        monkeypatch.setattr(rl.time, "monotonic", lambda: fake["t"])
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
