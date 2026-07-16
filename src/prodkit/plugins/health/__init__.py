"""Health plugin: Kubernetes-native endpoints.

- /live   → 200 if the process is alive (liveness probe)
- /health → alias for liveness, the conventional human-checked URL
- /ready  → 200 only when every registered plugin check passes; 503 with
            per-check detail otherwise (readiness probe)
"""

from __future__ import annotations

import inspect
from typing import Any, ClassVar

from starlette.responses import JSONResponse

from prodkit.contracts.plugin import Check, Plugin
from prodkit.core.context import Context
from prodkit.core.exceptions import ProdKitError


class HealthPlugin(Plugin):
    name: ClassVar[str] = "health"

    def __init__(self) -> None:
        self._ctx: Context | None = None
        self._plugins: list[Plugin] = []

    def configure(self, ctx: Context) -> None:
        self._ctx = ctx
        # The health plugin aggregates checks from every active plugin; the
        # registry hands us the list without coupling to the plugin manager.
        ctx.registry.provide("health", self)

    def register_plugins(self, plugins: list[Plugin]) -> None:
        self._plugins = plugins

    async def run_checks(self) -> list[Check]:
        if self._ctx is None:  # pragma: no cover - configure() always runs first
            raise ProdKitError("HealthPlugin used before configure()")
        results: list[Check] = []
        for plugin in self._plugins:
            checks = plugin.checks(self._ctx)
            if inspect.isawaitable(checks):
                checks = await checks
            results.extend(checks)
        return results

    def register_routes(self, ctx: Context) -> None:
        cfg = ctx.config.health

        async def live() -> JSONResponse:
            return JSONResponse({"status": "alive"})

        async def health() -> JSONResponse:
            return JSONResponse({"status": "ok"})

        async def ready() -> JSONResponse:
            checks = await self.run_checks()
            failed = [c for c in checks if not c.passed]
            payload: dict[str, Any] = {
                "status": "ready" if not failed else "not ready",
                "checks": [
                    {"name": c.name, "passed": c.passed, "detail": c.detail} for c in checks
                ],
            }
            return JSONResponse(payload, status_code=200 if not failed else 503)

        # Excluded from the OpenAPI schema: probe endpoints are infrastructure,
        # not API surface.
        ctx.app.add_api_route(cfg.live_path, live, include_in_schema=False)
        ctx.app.add_api_route(cfg.health_path, health, include_in_schema=False)
        ctx.app.add_api_route(cfg.ready_path, ready, include_in_schema=False)
