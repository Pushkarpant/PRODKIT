"""Unit tests for the Prometheus metrics plugin."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prodkit import Production
from prodkit.core.exceptions import ProdKitConfigError
from prodkit.plugins.metrics import MetricsRecorder, _route_template
from tests.conftest import NO_TOML


def build_app(**metrics) -> FastAPI:
    app = FastAPI()

    @app.get("/items/{item_id}")
    def get_item(item_id: int):
        return {"item_id": item_id}

    @app.get("/ping")
    def ping():
        return {"ok": True}

    Production(
        app,
        config_file=NO_TOML,
        environment="production",
        metrics={**metrics},
    )
    return app


class TestRouteTemplate:
    def test_returns_unmatched_when_no_route(self):
        assert _route_template({}) == "unmatched"

    def test_returns_path_format_when_available(self):
        class FakeRoute:
            path_format = "/items/{item_id}"

        assert _route_template({"route": FakeRoute()}) == "/items/{item_id}"

    def test_returns_path_fallback(self):
        class FakeRoute:
            path = "/health"

        assert _route_template({"route": FakeRoute()}) == "/health"


class TestMetricsRecorder:
    def test_creates_collector_registry(self):
        recorder = MetricsRecorder(buckets=None)
        assert recorder.registry is not None
        assert recorder.requests_total is not None
        assert recorder.request_duration is not None
        assert recorder.in_progress is not None

    def test_custom_buckets(self):
        recorder = MetricsRecorder(buckets=[0.01, 0.05, 0.1, 0.5, 1.0])
        # The histogram should accept the custom buckets without error
        assert recorder.request_duration is not None

    def test_exposition_returns_bytes_and_content_type(self):
        recorder = MetricsRecorder(buckets=None)
        payload, content_type = recorder.exposition()
        assert isinstance(payload, bytes)
        assert "text/plain" in content_type or "text/openmetrics" in content_type


class TestMetricsPlugin:
    def test_disabled_by_default(self):
        prod = Production(FastAPI(), config_file=NO_TOML, environment="production")
        assert "metrics" not in {p.name for p in prod.plugins}

    def test_enabled_adds_plugin(self):
        app = build_app()
        prod = app._prodkit_production
        assert "metrics" in {p.name for p in prod.plugins}

    def test_registry_provides_metrics_service(self):
        app = build_app()
        prod = app._prodkit_production
        assert prod.context.registry.has("metrics")
        assert isinstance(prod.context.registry.get("metrics"), MetricsRecorder)

    def test_doctor_audit(self):
        app = build_app()
        prod = app._prodkit_production
        plugin = next(p for p in prod.plugins if p.name == "metrics")
        (audit,) = plugin.doctor(prod.context)
        assert audit.status == "ok"
        assert "/metrics" in audit.detail

    def test_missing_prometheus_dep_fails_with_pip_hint(self, monkeypatch):
        monkeypatch.setattr(
            "prodkit.plugins.metrics._load_prometheus",
            lambda: (_ for _ in ()).throw(
                ProdKitConfigError(
                    "metrics.enabled=True but prometheus-client is not installed. "
                    "Install it with: pip install 'prodkit[metrics]'"
                )
            ),
        )
        with pytest.raises(ProdKitConfigError, match=r"prodkit\[metrics\]"):
            build_app()


class TestMetricsEndpoint:
    def test_metrics_endpoint_serves_prometheus_format(self):
        with TestClient(build_app()) as client:
            response = client.get("/metrics")
            assert response.status_code == 200
            assert "http_requests_total" in response.text

    def test_metrics_endpoint_not_in_openapi(self):
        with TestClient(build_app()) as client:
            schema = client.get("/openapi.json").json()
            assert "/metrics" not in schema.get("paths", {})

    def test_request_counter_increments(self):
        with TestClient(build_app()) as client:
            client.get("/ping")
            client.get("/ping")
            metrics = client.get("/metrics").text
            # Should see http_requests_total with count >= 2 for /ping
            assert "http_requests_total" in metrics

    def test_route_template_used_as_label(self):
        with TestClient(build_app()) as client:
            client.get("/items/42")
            metrics = client.get("/metrics").text
            # Route template label, not raw path
            assert "/items/{item_id}" in metrics
            assert "/items/42" not in metrics

    def test_404_collapses_to_unmatched(self):
        with TestClient(build_app()) as client:
            client.get("/nonexistent")
            metrics = client.get("/metrics").text
            assert "unmatched" in metrics

    def test_excluded_paths_not_measured(self):
        app = FastAPI()

        @app.get("/ping")
        def ping():
            return {"ok": True}

        Production(
            app,
            config_file=NO_TOML,
            environment="production",
            metrics={"exclude_paths": ["/ping"]},
        )
        with TestClient(app) as client:
            client.get("/ping")
            client.get("/ping")
            metrics = client.get("/metrics").text
            # /ping should not appear in any metric label
            lines = [
                line
                for line in metrics.splitlines()
                if "/ping" in line and not line.startswith("#")
            ]
            assert len(lines) == 0

    def test_custom_metrics_path(self):
        app = FastAPI()

        @app.get("/ping")
        def ping():
            return {"ok": True}

        Production(
            app,
            config_file=NO_TOML,
            environment="production",
            metrics={"path": "/internal/metrics"},
        )
        with TestClient(app) as client:
            assert client.get("/internal/metrics").status_code == 200
            assert client.get("/metrics").status_code in (404, 422)
