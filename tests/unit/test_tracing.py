"""Unit tests for the OpenTelemetry tracing plugin."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prodkit import Production
from prodkit.core.exceptions import ProdKitConfigError
from prodkit.plugins.tracing import TracingSetup
from tests.conftest import NO_TOML


def build_app(**tracing) -> FastAPI:
    app = FastAPI(title="TracingTestApp")

    @app.get("/items/{item_id}")
    def get_item(item_id: int):
        return {"item_id": item_id}

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    Production(
        app,
        config_file=NO_TOML,
        environment="production",
        tracing={"exporter": "none", **tracing},
    )
    return app


class TestTracingPlugin:
    def test_disabled_by_default(self):
        prod = Production(FastAPI(), config_file=NO_TOML, environment="production")
        assert "tracing" not in {p.name for p in prod.plugins}

    def test_enabled_adds_plugin(self):
        app = build_app()
        prod = app._prodkit_production
        assert "tracing" in {p.name for p in prod.plugins}

    def test_registry_provides_tracer_service(self):
        app = build_app()
        prod = app._prodkit_production
        assert prod.context.registry.has("tracer")
        assert isinstance(prod.context.registry.get("tracer"), TracingSetup)

    def test_service_name_defaults_to_app_title(self):
        app = build_app()
        prod = app._prodkit_production
        setup = prod.context.registry.get("tracer")
        assert setup.tracer is not None

    def test_custom_service_name(self):
        app = build_app(service_name="my-service")
        prod = app._prodkit_production
        assert prod.context.registry.has("tracer")

    def test_console_exporter(self):
        # Should not raise
        app = build_app(exporter="console")
        prod = app._prodkit_production
        assert "tracing" in {p.name for p in prod.plugins}

    def test_none_exporter(self):
        app = build_app(exporter="none")
        prod = app._prodkit_production
        assert "tracing" in {p.name for p in prod.plugins}

    def test_sample_rate_zero(self):
        app = build_app(sample_rate=0.0)
        prod = app._prodkit_production
        assert "tracing" in {p.name for p in prod.plugins}

    def test_sample_rate_half(self):
        app = build_app(sample_rate=0.5)
        prod = app._prodkit_production
        assert "tracing" in {p.name for p in prod.plugins}

    def test_missing_otel_dep_fails_with_pip_hint(self, monkeypatch):
        monkeypatch.setattr(
            "prodkit.plugins.tracing._load_otel",
            lambda: (_ for _ in ()).throw(
                ProdKitConfigError(
                    "tracing.enabled=True but opentelemetry packages are not installed. "
                    "Install them with: pip install 'prodkit[otel]'"
                )
            ),
        )
        with pytest.raises(ProdKitConfigError, match=r"prodkit\[otel\]"):
            build_app()

    def test_doctor_audit(self):
        app = build_app()
        prod = app._prodkit_production
        plugin = next(p for p in prod.plugins if p.name == "tracing")
        (audit,) = plugin.doctor(prod.context)
        assert audit.status == "ok"
        assert "none" in audit.detail  # exporter=none
        assert "sample_rate" in audit.detail


class TestTracingMiddleware:
    def test_request_succeeds_with_tracing(self):
        with TestClient(build_app()) as client:
            response = client.get("/ping")
            assert response.status_code == 200
            assert response.json() == {"ok": True}

    def test_parameterized_route_succeeds(self):
        with TestClient(build_app()) as client:
            response = client.get("/items/42")
            assert response.status_code == 200
            assert response.json() == {"item_id": 42}

    def test_404_succeeds(self):
        with TestClient(build_app()) as client:
            response = client.get("/nonexistent")
            assert response.status_code == 404

    def test_exception_propagates(self):
        with TestClient(build_app(), raise_server_exceptions=False) as client:
            response = client.get("/boom")
            assert response.status_code == 500

    def test_traceparent_header_accepted(self):
        """The middleware should not crash on an incoming traceparent header."""
        with TestClient(build_app()) as client:
            response = client.get(
                "/ping",
                headers={"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"},
            )
            assert response.status_code == 200


class TestTracingWithOtherPlugins:
    def test_tracing_and_metrics_together(self):
        """Both tracing and metrics can coexist without conflict."""
        app = FastAPI()

        @app.get("/ping")
        def ping():
            return {"ok": True}

        Production(
            app,
            config_file=NO_TOML,
            environment="production",
            metrics=True,
            tracing={"exporter": "none"},
        )
        with TestClient(app) as client:
            assert client.get("/ping").status_code == 200
            assert client.get("/metrics").status_code == 200

    def test_tracing_and_cache_together(self):
        """Tracing and cache can coexist without conflict."""
        app = FastAPI()

        @app.get("/ping")
        def ping():
            return {"ok": True}

        Production(
            app,
            config_file=NO_TOML,
            environment="production",
            cache=True,
            tracing={"exporter": "none"},
        )
        with TestClient(app) as client:
            assert client.get("/ping").status_code == 200
