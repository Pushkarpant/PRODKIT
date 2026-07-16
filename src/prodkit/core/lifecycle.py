"""Lifespan composition: ProdKit startup wraps the user's existing lifespan.

Order guarantee:
    plugin startup (dependency order)
        → user lifespan enter
            → requests
        → user lifespan exit
    plugin shutdown (reverse order, LIFO)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

    from prodkit.contracts.plugin import Plugin
    from prodkit.core.context import Context

logger = logging.getLogger("prodkit")


def compose_lifespan(
    app: FastAPI, ctx: Context, plugins: list[Plugin]
) -> Callable[[FastAPI], Any]:
    existing_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app_: FastAPI) -> AsyncIterator[Any]:
        async with AsyncExitStack() as stack:
            started: list[Plugin] = []

            async def _shutdown_all() -> None:
                for plugin in reversed(started):
                    try:
                        await plugin.shutdown(ctx)
                    except Exception:
                        # One plugin's failing shutdown must not prevent the
                        # rest from releasing their resources.
                        logger.exception("Shutdown failed for plugin %r", plugin.name)

            stack.push_async_callback(_shutdown_all)
            for plugin in plugins:
                await plugin.startup(ctx)
                started.append(plugin)

            state = await stack.enter_async_context(existing_lifespan(app_))
            yield state

    return lifespan
