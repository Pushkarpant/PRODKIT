"""OpenTelemetry tracing plugin: automatic request spans with context propagation.

Creates a span per HTTP request with standard semantic conventions, propagates
incoming W3C ``traceparent`` headers, and exports via OTLP (default), console,
or ``none`` (disabled exporter for testing). The ``TracerProvider`` is published
in the registry as ``\"tracer\"`` so custom code can create child spans::

    tracer = ctx.registry.get("tracer").tracer
    with tracer.start_as_current_span("my-operation"):
        ...

Like every optional-extra plugin, the OpenTelemetry packages are imported lazily
at ``configure()`` time — a missing install fails at boot with a pip hint, never
at request time.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from prodkit.contracts.plugin import PRIORITY_TRACING, Audit, Plugin
from prodkit.core.context import Context
from prodkit.core.exceptions import ProdKitConfigError

logger = logging.getLogger("prodkit")


def _load_otel() -> tuple[Any, ...]:
    """Import the required opentelemetry packages, or fail with a pip hint.

    Returns ``(trace, TracerProvider, sampler_module, exporters_dict)``
    where *exporters_dict* maps exporter names to lazy factories.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace import sampling as sampler_module
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )
    except ImportError:
        raise ProdKitConfigError(
            "tracing.enabled=True but opentelemetry packages are not installed. "
            "Install them with: pip install 'prodkit[otel]'"
        ) from None
    return (
        trace,
        TracerProvider,
        sampler_module,
        BatchSpanProcessor,
        SimpleSpanProcessor,
        ConsoleSpanExporter,
    )


class TracingSetup:
    """Holds the configured TracerProvider and tracer for registry publication."""

    def __init__(self, provider: Any, tracer: Any) -> None:
        self.provider = provider
        self.tracer = tracer


class TracingMiddleware:
    """Pure-ASGI middleware that creates a span per HTTP request.

    Runs at PRIORITY_TRACING (290), inside logging/errors, outside metrics.
    Propagates incoming ``traceparent`` headers per W3C Trace Context.
    """

    def __init__(self, app: Any, tracer: Any) -> None:
        self.app = app
        self.tracer = tracer

    def _route_template(self, scope: dict[str, Any]) -> str:
        route = scope.get("route")
        if route is None:
            return "unmatched"
        template = getattr(route, "path_format", None) or getattr(route, "path", None)
        return template or "unmatched"

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        path = scope.get("path", "/")

        # Extract incoming trace context (W3C traceparent) if present
        token = None
        try:
            from opentelemetry import context as otel_context
            from opentelemetry.propagate import extract

            headers = dict(scope.get("headers", []))
            # Convert headers from bytes to str for extraction
            carrier: dict[str, str] = {}
            for k, v in headers.items():
                key = k.decode("utf-8") if isinstance(k, bytes) else k
                val = v.decode("utf-8") if isinstance(v, bytes) else v
                carrier[key] = val
            ctx = extract(carrier)
            token = otel_context.attach(ctx)
        except Exception:  # noqa: S110
            pass

        span_name = f"{method} {path}"
        status_code = 500
        try:
            with self.tracer.start_as_current_span(
                span_name,
                attributes={
                    "http.method": method,
                    "http.url": path,
                    "http.scheme": scope.get("scheme", "http"),
                },
            ) as span:

                async def send_capturing_status(message: dict[str, Any]) -> None:
                    nonlocal status_code
                    if message["type"] == "http.response.start":
                        status_code = message["status"]
                    await send(message)

                try:
                    await self.app(scope, receive, send_capturing_status)
                except Exception as exc:
                    span.set_attribute("error", True)
                    span.record_exception(exc)
                    raise
                finally:
                    route_path = self._route_template(scope)
                    span.set_attribute("http.route", route_path)
                    span.set_attribute("http.status_code", status_code)
        finally:
            if token is not None:
                try:
                    from opentelemetry import context as otel_context

                    otel_context.detach(token)
                except Exception:  # noqa: S110
                    pass


class TracingPlugin(Plugin):
    """OpenTelemetry tracing: automatic request spans with OTLP/console export."""

    name: ClassVar[str] = "tracing"

    def __init__(self) -> None:
        self._setup: TracingSetup | None = None
        self._modules: tuple[Any, ...] | None = None

    def configure(self, ctx: Context) -> None:
        cfg = ctx.config.tracing
        modules = _load_otel()
        self._modules = modules
        (
            trace,
            tracer_provider_cls,
            sampler_module,
            batch_span_processor_cls,
            simple_span_processor_cls,
            console_span_exporter_cls,
        ) = modules

        # Configure sampler
        if cfg.sample_rate >= 1.0:
            sampler = sampler_module.ALWAYS_ON
        elif cfg.sample_rate <= 0.0:
            sampler = sampler_module.ALWAYS_OFF
        else:
            sampler = sampler_module.TraceIdRatioBased(cfg.sample_rate)

        provider = tracer_provider_cls(sampler=sampler)

        # Configure exporter
        if cfg.exporter == "console":
            provider.add_span_processor(simple_span_processor_cls(console_span_exporter_cls()))
        elif cfg.exporter == "otlp":
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore
                    OTLPSpanExporter,
                )
            except ImportError:
                raise ProdKitConfigError(
                    "tracing.exporter='otlp' requires opentelemetry-exporter-otlp-proto-grpc. "
                    "Install it with: pip install 'prodkit[otel]'"
                ) from None
            kwargs: dict[str, Any] = {}
            if cfg.endpoint is not None:
                kwargs["endpoint"] = cfg.endpoint
            provider.add_span_processor(batch_span_processor_cls(OTLPSpanExporter(**kwargs)))
        # exporter == "none": no processor, spans are created but not exported

        trace.set_tracer_provider(provider)

        service_name = cfg.service_name or getattr(ctx.app, "title", None) or "prodkit-app"
        tracer = trace.get_tracer(service_name)

        self._setup = TracingSetup(provider, tracer)
        ctx.registry.provide("tracer", self._setup)

    def register_middleware(self, ctx: Context) -> None:
        assert self._setup is not None  # noqa: S101 - configure() runs first
        ctx.add_middleware(
            TracingMiddleware,
            priority=PRIORITY_TRACING,
            tracer=self._setup.tracer,
        )

    async def shutdown(self, ctx: Context) -> None:
        if self._setup is not None and self._setup.provider is not None:
            self._setup.provider.shutdown()

    def doctor(self, ctx: Context) -> list[Audit]:
        cfg = ctx.config.tracing
        service = cfg.service_name or "(app title)"
        detail_msg = f"{cfg.exporter} exporter, sample_rate={cfg.sample_rate}, service={service}"
        return [
            Audit(
                name="Tracing",
                status="ok",
                detail=detail_msg,
                weight=8,
            )
        ]
