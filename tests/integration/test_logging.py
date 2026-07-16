"""Integration tests for structured logging and middleware ordering."""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from tests.conftest import make_app


class TestAccessLog:
    def test_json_access_log_line_with_request_id(self, capsys):
        client = TestClient(make_app())
        response = client.get("/hello")
        request_id = response.headers["X-Request-ID"]

        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        access = [entry for entry in lines if entry.get("path") == "/hello"]
        assert len(access) == 1
        entry = access[0]
        assert entry["method"] == "GET"
        assert entry["status"] == 200
        assert entry["duration_ms"] >= 0
        assert entry["request_id"] == request_id
        assert entry["level"] == "INFO"

    def test_log_injection_neutralized(self, capsys):
        client = TestClient(make_app())
        # %0A / %0D decode to newline/CR in the path; must not forge log lines
        client.get("/hello%0Afake-log-entry")
        out = capsys.readouterr().out
        for line in out.splitlines():
            json.loads(line)  # every line is intact JSON — nothing injected
        assert "\nfake-log-entry" not in out

    def test_console_format_in_development(self, capsys):
        client = TestClient(make_app(environment="development"))
        client.get("/hello")
        out = capsys.readouterr().out
        assert "GET /hello 200" in out
        # console lines are not JSON
        assert not out.lstrip().startswith("{")

    def test_exception_traceback_goes_to_logs(self, capsys):
        client = TestClient(make_app(), raise_server_exceptions=False)
        client.get("/boom")
        out = capsys.readouterr().out
        entries = [json.loads(line) for line in out.splitlines()]
        errors = [e for e in entries if e["level"] == "ERROR"]
        assert len(errors) == 1
        assert "secret internal detail" in errors[0]["exception"]
        assert errors[0]["request_id"]  # correlated to the request


class TestMiddlewareOrdering:
    def test_request_id_wraps_logging(self):
        """Middleware sorted by priority: request-id (100) must be outermost
        so the access log (200) sees the ID. Verified structurally."""
        app = make_app()
        stack_classes = [m.cls.__name__ for m in app.user_middleware]
        rid = stack_classes.index("RequestIDMiddleware")
        log = stack_classes.index("AccessLogMiddleware")
        gzip = stack_classes.index("GZipMiddleware")
        # In user_middleware, earlier = outermost.
        assert rid < log < gzip

    def test_logging_still_works_without_request_id_plugin(self, capsys):
        client = TestClient(make_app(request_id=False))
        client.get("/hello")
        entries = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        access = [e for e in entries if e.get("path") == "/hello"]
        assert len(access) == 1
        assert "request_id" not in access[0]  # degrades gracefully

    def teardown_method(self):
        # configure_logging replaces handlers per app; reset so capsys state
        # doesn't leak between tests
        for name in ("prodkit", "prodkit.access"):
            logging.getLogger(name).handlers = []
