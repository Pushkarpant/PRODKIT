"""The Production entrypoint — ProdKit's public API.

from fastapi import FastAPI
from prodkit import Production

app = FastAPI()
Production(app)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from prodkit.contracts.plugin import Plugin
from prodkit.core.config import ProdKitConfig, resolve_config
from prodkit.core.context import Context
from prodkit.core.exceptions import ProdKitError
from prodkit.core.lifecycle import compose_lifespan
from prodkit.core.plugin_manager import PluginManager

if TYPE_CHECKING:
    from fastapi import FastAPI

_MARKER_ATTR = "_prodkit_production"

# The built-in plugin factory is injected by prodkit/__init__.py so the kernel
# stays free of plugin imports (enforced by import-linter).
_builtin_factory: Callable[[ProdKitConfig], list[Plugin]] = lambda config: []  # noqa: E731


def set_builtin_factory(factory: Callable[[ProdKitConfig], list[Plugin]]) -> None:
    global _builtin_factory
    _builtin_factory = factory


# Plugin sections that can be toggled with Production(app, cors=False) etc.
_TOGGLEABLE = (
    "logging",
    "request_id",
    "errors",
    "health",
    "security",
    "cors",
    "compression",
)


class Production:
    """Configure production best practices on a FastAPI application.

    Args:
        app: The FastAPI application to productionize (mutated in place).
        plugins: Additional plugins, activated after the built-ins.
        config_file: Path to the TOML config file (default ``prodkit.toml``).
        environment: ``"development"``, ``"staging"``, or ``"production"``.
        **overrides: Top-level config overrides. Booleans toggle a section
            (``cors=False``); dicts configure it
            (``cors={"origins": ["https://app.example.com"]}``).
    """

    def __init__(
        self,
        app: FastAPI,
        *,
        plugins: list[Plugin] | None = None,
        config_file: str | Path = "prodkit.toml",
        environment: str | None = None,
        **overrides: Any,
    ) -> None:
        if getattr(app, _MARKER_ATTR, None) is not None:
            raise ProdKitError("Production() was already applied to this app")

        self.config = resolve_config(
            self._normalize_overrides(environment, overrides), toml_path=config_file
        )
        self.context = Context(app, self.config)

        all_plugins = _builtin_factory(self.config) + list(plugins or [])
        self.plugins = PluginManager(all_plugins).plugins

        self._boot(app)
        setattr(app, _MARKER_ATTR, self)

    @staticmethod
    def _normalize_overrides(environment: str | None, overrides: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        if environment is not None:
            normalized["environment"] = environment
        for key, value in overrides.items():
            if key in _TOGGLEABLE and isinstance(value, bool):
                normalized[key] = {"enabled": value}
            elif key in _TOGGLEABLE and isinstance(value, dict):
                normalized[key] = {"enabled": True, **value}
            else:
                normalized[key] = value
        return normalized

    def _boot(self, app: FastAPI) -> None:
        ctx = self.context
        for plugin in self.plugins:
            ctx._current_plugin = plugin.name
            plugin.configure(ctx)
        for plugin in self.plugins:
            ctx._current_plugin = plugin.name
            plugin.register_middleware(ctx)
        ctx._current_plugin = ""

        # The health plugin aggregates readiness checks from all plugins; hand
        # it the activated list via its registry-published interface.
        if ctx.registry.has("health"):
            ctx.registry.get("health").register_plugins(self.plugins)

        # Starlette applies middleware inside-out (last added = outermost),
        # so apply in DESCENDING priority: highest (innermost) first.
        for spec in sorted(ctx.middleware_specs(), key=lambda s: s.priority, reverse=True):
            app.add_middleware(spec.cls, **spec.options)  # type: ignore[arg-type]

        for plugin in self.plugins:
            plugin.register_routes(ctx)

        app.router.lifespan_context = compose_lifespan(app, ctx, self.plugins)
