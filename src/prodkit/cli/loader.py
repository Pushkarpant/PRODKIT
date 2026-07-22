"""Load a user's ``Production``-configured app for CLI inspection.

Resolves a Uvicorn-style ``"module:attribute"`` import string (with autodetect
fallbacks), imports it, and returns the :class:`~prodkit.core.production.Production`
instance ProdKit stamped onto the app — the single object holding the resolved
config, active plugins, and middleware order the CLI reports on.
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import TYPE_CHECKING, cast

from prodkit.core.production import _MARKER_ATTR

if TYPE_CHECKING:
    from prodkit.core.production import Production

# Tried in order when the user doesn't pass --app. Mirrors Uvicorn conventions.
_DEFAULT_CANDIDATES = ("main:app", "app:app", "asgi:app", "app.main:app")


class AppLoadError(RuntimeError):
    """Raised when the target app can't be found or has no ProdKit applied."""


def _import_target(spec: str) -> object | None:
    """Import ``module:attr`` and return the attribute, or None if unimportable."""
    module_name, _, attr = spec.partition(":")
    attr = attr or "app"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        return None
    return getattr(module, attr, None)


def load_production(spec: str | None) -> Production:
    """Return the ``Production`` instance for the target app.

    Args:
        spec: ``"module:attr"`` import string, or None to autodetect.

    Raises:
        AppLoadError: with an actionable message if the app or its ProdKit
            configuration can't be located.
    """
    # The user's app lives in the current working directory, not the install.
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    candidates = [spec] if spec else list(_DEFAULT_CANDIDATES)
    app = None
    for candidate in candidates:
        app = _import_target(candidate)
        if app is not None:
            break

    if app is None:
        tried = ", ".join(candidates)
        raise AppLoadError(
            f"Could not import a FastAPI app (tried: {tried}). "
            "Pass --app module:attribute pointing at your FastAPI instance."
        )

    production = getattr(app, _MARKER_ATTR, None)
    if production is None:
        raise AppLoadError(
            "Found the app but Production() was never applied to it. "
            "Add `Production(app)` so ProdKit can audit it."
        )
    return cast("Production", production)
