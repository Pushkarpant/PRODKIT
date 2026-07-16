"""Built-in plugin composition.

This module (not the kernel) knows about the concrete built-in plugins.
``prodkit/__init__.py`` injects :func:`builtin_plugins` into the kernel at
import time, keeping ``prodkit.core`` free of plugin imports (enforced by
import-linter).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prodkit.plugins.compression import CompressionPlugin
from prodkit.plugins.cors import CORSPlugin
from prodkit.plugins.errors import ErrorsPlugin
from prodkit.plugins.health import HealthPlugin
from prodkit.plugins.logging import LoggingPlugin
from prodkit.plugins.request_id import RequestIDPlugin
from prodkit.plugins.security import SecurityPlugin

if TYPE_CHECKING:
    from prodkit.contracts.plugin import Plugin
    from prodkit.core.config import ProdKitConfig

__all__ = [
    "CORSPlugin",
    "CompressionPlugin",
    "ErrorsPlugin",
    "HealthPlugin",
    "LoggingPlugin",
    "RequestIDPlugin",
    "SecurityPlugin",
    "builtin_plugins",
]


def builtin_plugins(config: ProdKitConfig) -> list[Plugin]:
    """The built-in plugins enabled by the given configuration."""
    plugins: list[Plugin] = []
    if config.request_id.enabled:
        plugins.append(RequestIDPlugin())
    if config.logging.enabled:
        plugins.append(LoggingPlugin())
    if config.errors.enabled:
        plugins.append(ErrorsPlugin())
    if config.health.enabled:
        plugins.append(HealthPlugin())
    if config.security.enabled:
        plugins.append(SecurityPlugin())
    if config.cors.enabled:
        plugins.append(CORSPlugin())
    if config.compression.enabled:
        plugins.append(CompressionPlugin())
    return plugins
