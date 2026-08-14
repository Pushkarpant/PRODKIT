"""Prometheus metrics plugin: request count, latency, and in-flight gauge.

Exposes ``/metrics`` in the standard exposition format. Metrics live in a
**dedicated** ``CollectorRegistry`` per :class:`Production` instance — never
prometheus-client's process-global default registry — so multiple apps in one
process (tests, embedded tooling) cannot collide, and users instrumenting with
the default registry elsewhere are unaffected. The registry is published as
service ``"metrics"`` so custom collectors can be added::

    ctx.registry.get("metrics").registry  # a prometheus CollectorRegistry

Path labels use the matched **route template** (``/items/{item_id}``), never
the raw path — unmatched requests (404s, scanner noise) all collapse into the
single label ``unmatched`` so cardinality stays bounded.

Limitation: with multiple workers each process serves its own counters from
``/metrics``; Prometheus' multiprocess file-backed mode is not supported yet.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, ClassVar

from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from prodkit.contracts.plugin import PRIORITY_METRICS, Audit, Plugin
from prodkit.core.context import Context
from prodkit.core.exceptions import ProdKitConfigError

if TYPE_CHECKING:
    from types import ModuleType


def _load_prometheus() -> ModuleType:
    """Import prometheus_client, or fail with the pip hint (monkeypatchable seam)."""
    try:
        import prometheus_client
    except ImportError:
        raise ProdKitConfigError(
            "metrics.enabled=True but prometheus-client is not installed. "
            "Install it with: pip install 'prodkit[metrics]'"
        ) from None
    return prometheus_client


def _route_template(scope: Scope) -> str:
    """The matched route's template path, or 'unmatched' (cardinality bound)."""
    route = scope.get("route")
    if route is None:
        return "unmatched"
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    return template or "unmatched"


class MetricsRecorder:
    """Owns the CollectorRegistry and the three HTTP metric families."""

    def __init__(self, buckets: list[float] | None) -> None:
        prometheus = _load_prometheus()
        self._prometheus = prometheus
        self.registry = prometheus.CollectorRegistry()
        self.requests_total = prometheus.Counter(
            "http_requests_total",
            "Total HTTP requests",
            ["method", "path", "status"],
            registry=self.registry,
        )
        histogram_kwargs: dict[str, Any] = {}
        if buckets is not None:
            histogram_kwargs["buckets"] = buckets
        self.request_duration = prometheus.Histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "path"],
            registry=self.registry,
            **histogram_kwargs,
        )
        self.in_progress = prometheus.Gauge(
            "http_requests_in_progress",
            "HTTP requests currently being served",
            ["method"],
            registry=self.registry,
        )

    def exposition(self) -> tuple[bytes, str]:
        return (
            self._prometheus.generate_latest(self.registry),
            self._prometheus.CONTENT_TYPE_LATEST,
        )


class MetricsMiddleware:
    """Pure-ASGI middleware (no BaseHTTPMiddleware overhead) measuring every
    HTTP request. Runs at PRIORITY_METRICS, inside request-id/logging."""

    def __init__(self, app: ASGIApp, recorder: MetricsRecorder, exclude: frozenset[str]) -> None:
        self.app = app
        self.recorder = recorder
        self.exclude = exclude

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.exclude:
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        status = "500"  # exceptions that propagate out count as 500s

        async def send_capturing_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = str(message["status"])
            await send(message)

        self.recorder.in_progress.labels(method).inc()
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_capturing_status)
        finally:
            duration = time.perf_counter() - start
            self.recorder.in_progress.labels(method).dec()
            # Routing happened inside the wrapped app; the scope now knows
            # the matched route (or lack of one).
            path = _route_template(scope)
            self.recorder.requests_total.labels(method, path, status).inc()
            self.recorder.request_duration.labels(method, path).observe(duration)


class MetricsPlugin(Plugin):
    name: ClassVar[str] = "metrics"

    def __init__(self) -> None:
        self._recorder: MetricsRecorder | None = None

    def configure(self, ctx: Context) -> None:
        # Building the recorder imports prometheus-client: a missing extra
        # fails here, at boot, with an actionable message.
        self._recorder = MetricsRecorder(ctx.config.metrics.buckets)
        ctx.registry.provide("metrics", self._recorder)

    def register_middleware(self, ctx: Context) -> None:
        cfg = ctx.config.metrics
        assert self._recorder is not None  # noqa: S101 - configure() runs first
        ctx.add_middleware(
            MetricsMiddleware,
            priority=PRIORITY_METRICS,
            recorder=self._recorder,
            # Scrapes must not count themselves.
            exclude=frozenset([cfg.path, *cfg.exclude_paths]),
        )

    def register_routes(self, ctx: Context) -> None:
        recorder = self._recorder
        assert recorder is not None  # noqa: S101 - configure() runs first

        async def metrics() -> Response:
            payload, content_type = recorder.exposition()
            return Response(payload, media_type=content_type)

        # Infrastructure endpoint, not API surface (same as health probes).
        ctx.app.add_api_route(ctx.config.metrics.path, metrics, include_in_schema=False)

    def doctor(self, ctx: Context) -> list[Audit]:
        return [
            Audit(
                name="Metrics",
                status="ok",
                detail=f"prometheus at {ctx.config.metrics.path}",
                weight=8,
            )
        ]
