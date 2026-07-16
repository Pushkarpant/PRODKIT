"""ProdKit exception hierarchy."""

from __future__ import annotations


class ProdKitError(Exception):
    """Base class for all ProdKit errors."""


class ProdKitConfigError(ProdKitError):
    """Raised when configuration is invalid. Aborts boot with a clear message."""


class PluginError(ProdKitError):
    """Raised when a plugin misbehaves (bad contract, failed hook)."""


class PluginDependencyError(PluginError):
    """Raised when plugin dependencies are missing or cyclic."""


class ServiceNotFoundError(ProdKitError):
    """Raised when a requested service is not in the registry."""
