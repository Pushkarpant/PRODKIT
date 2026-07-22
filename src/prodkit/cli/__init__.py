"""ProdKit command-line interface.

The heavy CLI (typer + rich) lives in :mod:`prodkit.cli.app`; this module keeps
only a thin ``run()`` entry point so that a base install without the ``cli``
extra fails with an actionable message instead of an import traceback.
"""

from __future__ import annotations

import sys

_CLI_DEPS = {"typer", "rich", "click"}


def run() -> None:
    """Console-script entry point (``prodkit``)."""
    try:
        from prodkit.cli.app import app
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised via packaging
        if exc.name in _CLI_DEPS:
            print(
                "The prodkit CLI requires extra dependencies.\n"
                "  Install them with:  pip install 'prodkit[cli]'",
                file=sys.stderr,
            )
            raise SystemExit(1) from None
        raise
    app()
