"""CORS plugin: thin, priority-ordered wrapper over Starlette's CORSMiddleware.

The dangerous combination (origins=['*'] + allow_credentials=True) is rejected
at config-resolution time in production.
"""

from __future__ import annotations

from typing import ClassVar

from starlette.middleware.cors import CORSMiddleware

from prodkit.contracts.plugin import PRIORITY_CORS, Audit, Plugin
from prodkit.core.context import Context
from prodkit.core.exceptions import ProdKitConfigError


class CORSPlugin(Plugin):
    name: ClassVar[str] = "cors"

    def configure(self, ctx: Context) -> None:
        if not ctx.config.cors.origins:
            raise ProdKitConfigError(
                "cors is enabled but no origins are configured; set "
                "cors={'origins': ['https://app.example.com']} or disable it"
            )

    def register_middleware(self, ctx: Context) -> None:
        cfg = ctx.config.cors
        ctx.add_middleware(
            CORSMiddleware,
            priority=PRIORITY_CORS,
            allow_origins=cfg.origins,
            allow_credentials=cfg.allow_credentials,
            allow_methods=cfg.allow_methods,
            allow_headers=cfg.allow_headers,
            max_age=cfg.max_age,
        )

    def doctor(self, ctx: Context) -> list[Audit]:
        cfg = ctx.config.cors
        wildcard = "*" in cfg.origins
        risky = wildcard and cfg.allow_credentials
        return [
            Audit(
                name="CORS",
                status="fail" if risky else ("warn" if wildcard else "ok"),
                detail=", ".join(cfg.origins) if cfg.origins else "no origins",
                recommendation=(
                    "list explicit origins; '*' with credentials lets any site call your API"
                    if wildcard
                    else ""
                ),
                weight=10,
            )
        ]
