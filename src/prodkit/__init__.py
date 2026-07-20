"""ProdKit — the production framework for FastAPI.

from fastapi import FastAPI
from prodkit import Production

app = FastAPI()
Production(app)
"""

from prodkit.contracts.plugin import Check, Plugin
from prodkit.core.config import (
    CompressionConfig,
    CORSConfig,
    ErrorsConfig,
    HealthConfig,
    LoggingConfig,
    ProdKitConfig,
    RequestIDConfig,
    SecurityConfig,
)
from prodkit.core.context import Context
from prodkit.core.exceptions import (
    PluginDependencyError,
    PluginError,
    ProdKitConfigError,
    ProdKitError,
    ServiceNotFoundError,
)
from prodkit.core.production import Production, set_builtin_factory
from prodkit.plugins import builtin_plugins

# Wire the built-in plugins into the kernel here, at the package composition
# root — the kernel itself never imports from prodkit.plugins.
set_builtin_factory(builtin_plugins)

__version__ = "0.1.3"

__all__ = [
    "CORSConfig",
    "Check",
    "CompressionConfig",
    "Context",
    "ErrorsConfig",
    "HealthConfig",
    "LoggingConfig",
    "Plugin",
    "PluginDependencyError",
    "PluginError",
    "ProdKitConfig",
    "ProdKitConfigError",
    "ProdKitError",
    "Production",
    "RequestIDConfig",
    "SecurityConfig",
    "ServiceNotFoundError",
    "__version__",
]
