"""Integration tests: real requests through a productionized app."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prodkit import ProdKitError, Production
from tests.conftest import NO_TOML, make_app


class TestOneLiner:
    def test_app_still_serves_user_routes(self):
        client = TestClient(make_app())
        response = client.get("/hello")
        assert response.status_code == 200
        assert response.json() == {"message": "hello"}

    def test_double_application_rejected(self):
        app = FastAPI()
        Production(app, config_file=NO_TOML)
        with pytest.raises(ProdKitError, match="already applied"):
            Production(app, config_file=NO_TOML)


class TestSecurityHeaders:
    def test_production_headers_present(self):
        client = TestClient(make_app())
        response = client.get("/hello")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert response.headers["X-XSS-Protection"] == "0"
        assert "max-age=63072000" in response.headers["Strict-Transport-Security"]

    def test_no_hsts_in_development(self):
        client = TestClient(make_app(environment="development"))
        response = client.get("/hello")
        assert "Strict-Transport-Security" not in response.headers

    def test_app_headers_not_overwritten(self):
        app = FastAPI()

        @app.get("/custom")
        def custom():
            from starlette.responses import JSONResponse

            return JSONResponse({}, headers={"X-Frame-Options": "SAMEORIGIN"})

        Production(app, config_file=NO_TOML)
        response = TestClient(app).get("/custom")
        # setdefault semantics: the app's own choice wins
        assert response.headers["X-Frame-Options"] == "SAMEORIGIN"

    def test_trusted_hosts_reject_unknown_host(self):
        client = TestClient(
            make_app(security={"trusted_hosts": ["api.example.com"]}),
            base_url="http://evil.example.com",
        )
        assert client.get("/hello").status_code == 400


class TestRequestID:
    def test_response_carries_generated_id(self):
        client = TestClient(make_app())
        response = client.get("/hello")
        assert len(response.headers["X-Request-ID"]) == 32

    def test_incoming_id_ignored_by_default(self):
        client = TestClient(make_app())
        response = client.get("/hello", headers={"X-Request-ID": "attacker-chosen"})
        assert response.headers["X-Request-ID"] != "attacker-chosen"

    def test_incoming_id_honored_when_trusted(self):
        client = TestClient(make_app(request_id={"trust_incoming": True}))
        response = client.get("/hello", headers={"X-Request-ID": "my-trace-42"})
        assert response.headers["X-Request-ID"] == "my-trace-42"

    def test_malformed_incoming_id_regenerated_even_when_trusted(self):
        client = TestClient(make_app(request_id={"trust_incoming": True}))
        response = client.get("/hello", headers={"X-Request-ID": "bad\tid with spaces"})
        assert response.headers["X-Request-ID"] != "bad\tid with spaces"


class TestErrors:
    def test_unhandled_exception_is_opaque_in_production(self):
        client = TestClient(make_app(), raise_server_exceptions=False)
        response = client.get("/boom")
        assert response.status_code == 500
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert body["title"] == "Internal Server Error"
        assert "secret internal detail" not in response.text
        assert "traceback" not in body
        assert body["request_id"]  # ops can correlate with logs

    def test_unhandled_exception_has_details_in_development(self):
        client = TestClient(make_app(environment="development"), raise_server_exceptions=False)
        body = client.get("/boom").json()
        assert body["detail"] == "secret internal detail"
        assert body["traceback"]

    def test_http_exception_shape(self):
        client = TestClient(make_app())
        response = client.get("/nonexistent")
        assert response.status_code == 404
        assert response.json()["title"] == "Not Found"

    def test_validation_error_shape(self):
        app = FastAPI()

        @app.get("/typed/{item_id}")
        def typed(item_id: int):
            return {"item_id": item_id}

        Production(app, config_file=NO_TOML)
        response = TestClient(app).get("/typed/not-a-number")
        assert response.status_code == 422
        assert response.json()["title"] == "Validation error"


class TestHealth:
    def test_liveness_endpoints(self):
        client = TestClient(make_app())
        assert client.get("/health").status_code == 200
        assert client.get("/live").status_code == 200

    def test_ready_passes_with_no_failing_checks(self):
        client = TestClient(make_app())
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    def test_ready_returns_503_when_a_check_fails(self):
        from prodkit import Check, Plugin

        class FailingPlugin(Plugin):
            name = "failing"

            def checks(self, ctx):
                return [Check(name="db", passed=False, detail="unreachable")]

        client = TestClient(make_app(plugins=[FailingPlugin()]))
        response = client.get("/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not ready"
        assert body["checks"][-1] == {
            "name": "db",
            "passed": False,
            "detail": "unreachable",
        }

    def test_health_endpoints_not_in_openapi(self):
        schema = TestClient(make_app()).get("/openapi.json").json()
        assert "/health" not in schema["paths"]
        assert "/ready" not in schema["paths"]


class TestCORS:
    def test_cors_disabled_by_default(self):
        client = TestClient(make_app())
        response = client.get("/hello", headers={"Origin": "https://evil.example.com"})
        assert "access-control-allow-origin" not in response.headers

    def test_cors_allows_configured_origin_only(self):
        client = TestClient(make_app(cors={"origins": ["https://app.example.com"]}))
        allowed = client.get("/hello", headers={"Origin": "https://app.example.com"})
        assert allowed.headers["access-control-allow-origin"] == "https://app.example.com"
        denied = client.get("/hello", headers={"Origin": "https://evil.example.com"})
        assert "access-control-allow-origin" not in denied.headers

    def test_cors_enabled_without_origins_fails_boot(self):
        from prodkit import ProdKitConfigError

        with pytest.raises(ProdKitConfigError, match="no origins"):
            make_app(cors=True)


class TestCompression:
    def test_large_response_gzipped(self):
        app = FastAPI()

        @app.get("/big")
        def big():
            return {"data": "x" * 5000}

        Production(app, config_file=NO_TOML)
        response = TestClient(app).get("/big", headers={"Accept-Encoding": "gzip"})
        assert response.headers["content-encoding"] == "gzip"
        assert response.json()["data"] == "x" * 5000

    def test_small_response_not_compressed(self):
        client = TestClient(make_app())
        response = client.get("/hello", headers={"Accept-Encoding": "gzip"})
        assert "content-encoding" not in response.headers


class TestLifespanComposition:
    def test_user_lifespan_preserved_and_ordered(self):
        from contextlib import asynccontextmanager

        events: list[str] = []

        @asynccontextmanager
        async def user_lifespan(app):
            events.append("user-start")
            yield
            events.append("user-stop")

        from prodkit import Plugin

        class TrackingPlugin(Plugin):
            name = "tracking"

            async def startup(self, ctx):
                events.append("plugin-start")

            async def shutdown(self, ctx):
                events.append("plugin-stop")

        app = FastAPI(lifespan=user_lifespan)
        Production(app, config_file=NO_TOML, plugins=[TrackingPlugin()])
        with TestClient(app):
            pass
        assert events == ["plugin-start", "user-start", "user-stop", "plugin-stop"]

    def test_toggled_off_plugins_stay_off(self):
        client = TestClient(make_app(security=False, compression=False))
        response = client.get("/hello")
        assert "X-Content-Type-Options" not in response.headers
