"""Minimal in-process pub/sub for cross-plugin signals."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("prodkit")

Handler = Callable[..., Any]


class EventBus:
    """Synchronous-by-default event bus; async handlers are awaited by
    :meth:`emit_async`. A failing handler is logged and skipped — one plugin's
    bug must not take down another's event handling."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}

    def subscribe(self, event: str, handler: Handler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, **payload: Any) -> None:
        for handler in self._handlers.get(event, []):
            if inspect.iscoroutinefunction(handler):
                raise TypeError(f"Handler {handler!r} for {event!r} is async; use emit_async()")
            try:
                handler(**payload)
            except Exception:
                logger.exception("Event handler failed for event %r", event)

    async def emit_async(self, event: str, **payload: Any) -> None:
        for handler in self._handlers.get(event, []):
            try:
                result = handler(**payload)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Event handler failed for event %r", event)
