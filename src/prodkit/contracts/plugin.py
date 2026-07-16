"""The Plugin contract every ProdKit plugin implements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from prodkit.core.context import Context


@dataclass
class Check:
    """A readiness/doctor check result."""

    name: str
    passed: bool
    detail: str = ""


class Plugin:
    """Base class for all ProdKit plugins. All hooks are optional overrides.

    Hooks run in dependency order (see ``requires``); ``shutdown`` runs in
    reverse activation order (LIFO).
    """

    name: ClassVar[str] = ""
    requires: ClassVar[tuple[str, ...]] = ()

    def configure(self, ctx: Context) -> None:
        """Validate and resolve configuration. Raise ProdKitConfigError to
        abort boot with a clear message."""

    def register_middleware(self, ctx: Context) -> None:
        """Register middleware via ``ctx.add_middleware(cls, priority=N, ...)``."""

    def register_routes(self, ctx: Context) -> None:
        """Add routes to ``ctx.app`` (e.g. /health)."""

    async def startup(self, ctx: Context) -> None:
        """Acquire async resources (connection pools, clients)."""

    async def shutdown(self, ctx: Context) -> None:
        """Release resources gracefully."""

    def checks(self, ctx: Context) -> list[Check]:
        """Readiness checks, aggregated by the health plugin's /ready."""
        return []


# Documented middleware priorities for the built-ins. Lower = outermost.
PRIORITY_REQUEST_ID = 100
PRIORITY_LOGGING = 200
PRIORITY_ERRORS = 250
PRIORITY_METRICS = 300
PRIORITY_SECURITY = 400
PRIORITY_CORS = 500
PRIORITY_RATE_LIMIT = 600
PRIORITY_COMPRESSION = 700
PRIORITY_AUTH = 800
