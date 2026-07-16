"""Shared fixtures. All integration tests build real apps through Production()."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI

from prodkit import Production

NO_TOML = Path("nonexistent-prodkit.toml")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_app(**overrides) -> FastAPI:
    """A minimal app with one route, productionized with the given overrides.
    Tests pass explicit config so the host machine's env/toml can't leak in."""
    app = FastAPI()

    @app.get("/hello")
    def hello():
        return {"message": "hello"}

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    overrides.setdefault("config_file", NO_TOML)
    Production(app, **overrides)
    return app
