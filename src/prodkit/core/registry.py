"""Named service registry shared across plugins."""

from __future__ import annotations

from typing import Any

from prodkit.core.exceptions import ProdKitError, ServiceNotFoundError


class Registry:
    """Simple name → service store. Names are unique; re-registration is an
    explicit error so two plugins can't silently fight over a name."""

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    def provide(self, name: str, service: Any) -> None:
        if name in self._services:
            raise ProdKitError(
                f"Service {name!r} is already registered; "
                "use a different name or remove the conflicting plugin"
            )
        self._services[name] = service

    def get(self, name: str) -> Any:
        try:
            return self._services[name]
        except KeyError:
            available = ", ".join(sorted(self._services)) or "<none>"
            raise ServiceNotFoundError(
                f"No service named {name!r}; available: {available}"
            ) from None

    def has(self, name: str) -> bool:
        return name in self._services

    def names(self) -> list[str]:
        return sorted(self._services)
