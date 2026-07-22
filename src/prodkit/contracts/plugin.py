"""The Plugin contract every ProdKit plugin implements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal

if TYPE_CHECKING:
    from prodkit.core.context import Context


@dataclass
class Check:
    """A runtime readiness result, aggregated by ``/ready`` (health plugin)."""

    name: str
    passed: bool
    detail: str = ""


AuditStatus = Literal["ok", "warn", "fail"]


@dataclass
class Audit:
    """A single production-readiness finding reported by ``prodkit doctor``.

    Distinct from :class:`Check`: ``Check`` answers "is this instance ready to
    serve traffic right now?" (a boolean liveness/readiness signal), whereas an
    ``Audit`` is a static configuration/security verdict with three states and a
    weighted contribution to the overall production score.

    Args:
        name: Human-readable name of the thing being audited.
        status: ``"ok"`` (full credit), ``"warn"`` (half credit — a soft
            recommendation), or ``"fail"`` (no credit — a real gap).
        detail: Short factual description of what was found.
        recommendation: What to change to reach ``"ok"`` (shown for warn/fail).
        weight: Relative contribution to the score. Higher = more important.
    """

    name: str
    status: AuditStatus
    detail: str = ""
    recommendation: str = ""
    weight: int = 10


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

    def doctor(self, ctx: Context) -> list[Audit]:
        """Static production-readiness findings for ``prodkit doctor``.

        Unlike :meth:`checks` (runtime readiness), these audit the resolved
        configuration and contribute to the production score. Optional override.
        """
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
