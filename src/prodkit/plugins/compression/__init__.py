"""Compression plugin: gzip via Starlette; innermost of the built-in
middleware so it compresses final response bodies."""

from __future__ import annotations

from typing import ClassVar

from starlette.middleware.gzip import GZipMiddleware

from prodkit.contracts.plugin import PRIORITY_COMPRESSION, Audit, Plugin
from prodkit.core.context import Context


class CompressionPlugin(Plugin):
    name: ClassVar[str] = "compression"

    def register_middleware(self, ctx: Context) -> None:
        ctx.add_middleware(
            GZipMiddleware,
            priority=PRIORITY_COMPRESSION,
            minimum_size=ctx.config.compression.minimum_size,
        )

    def doctor(self, ctx: Context) -> list[Audit]:
        return [
            Audit(
                name="Compression",
                status="ok",
                detail=f"gzip over {ctx.config.compression.minimum_size} bytes",
                weight=5,
            )
        ]
