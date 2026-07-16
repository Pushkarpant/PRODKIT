"""The Context object handed to every plugin hook."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from prodkit.core.event_bus import EventBus
from prodkit.core.registry import Registry

if TYPE_CHECKING:
    from fastapi import FastAPI

    from prodkit.core.config import ProdKitConfig


@dataclass
class MiddlewareSpec:
    """A deferred middleware registration; the kernel sorts these by priority
    (ascending = outermost first) before applying them to the app."""

    cls: type
    priority: int
    options: dict[str, Any] = field(default_factory=dict)
    plugin: str = ""


class Context:
    """Everything a plugin may touch: the app, config, registry, and events."""

    def __init__(self, app: FastAPI, config: ProdKitConfig) -> None:
        self.app = app
        self.config = config
        self.registry = Registry()
        self.events = EventBus()
        self._middleware: list[MiddlewareSpec] = []
        self._current_plugin: str = ""

    def add_middleware(self, cls: type, *, priority: int, **options: Any) -> None:
        """Register middleware with an explicit priority.

        Lower priority = outermost (runs first on requests, last on responses).
        Built-in priorities: request-id=100, logging=200, security=400,
        cors=500, compression=700.
        """
        self._middleware.append(
            MiddlewareSpec(
                cls=cls, priority=priority, options=options, plugin=self._current_plugin
            )
        )

    def middleware_specs(self) -> list[MiddlewareSpec]:
        return list(self._middleware)
