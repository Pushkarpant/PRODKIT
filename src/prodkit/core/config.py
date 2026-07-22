"""Layered configuration.

Resolution priority (highest wins):
    1. Python arguments to ``Production(...)``
    2. Environment variables (``PRODKIT_*``, ``__`` as section delimiter)
    3. ``prodkit.toml``
    4. Environment-profile defaults (development / staging / production)
    5. Library defaults declared on the models below
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10 in CI
    import tomli as tomllib

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from prodkit.core.exceptions import ProdKitConfigError

Environment = Literal["development", "staging", "production"]

_ENV_PREFIX = "PRODKIT_"


class _Section(BaseModel):
    """Base for config sections: unknown keys are a hard error (fail fast)."""

    model_config = ConfigDict(extra="forbid")


class LoggingConfig(_Section):
    enabled: bool = True
    level: str = "INFO"
    format: Literal["json", "console"] = "json"
    include_request_body: bool = False  # off by default: bodies may contain secrets/PII


class RequestIDConfig(_Section):
    enabled: bool = True
    header: str = "X-Request-ID"
    # Trusting inbound IDs lets clients forge/poison log correlation, so
    # only honor them from a proxy you control.
    trust_incoming: bool = False


class ErrorsConfig(_Section):
    enabled: bool = True
    # Debug tracebacks in responses are opt-in and refused in production (see checks below).
    include_debug_details: bool = False


class HealthConfig(_Section):
    enabled: bool = True
    health_path: str = "/health"
    ready_path: str = "/ready"
    live_path: str = "/live"


class SecurityConfig(_Section):
    enabled: bool = True
    hsts: bool = True
    hsts_max_age: int = 63072000  # 2 years, preload-eligible
    frame_options: Literal["DENY", "SAMEORIGIN"] = "DENY"
    referrer_policy: str = "strict-origin-when-cross-origin"
    content_security_policy: str | None = None  # opt-in: app-specific
    permissions_policy: str = "camera=(), microphone=(), geolocation=()"
    trusted_hosts: list[str] = Field(default_factory=list)
    https_redirect: bool = False


class CORSConfig(_Section):
    enabled: bool = False
    origins: list[str] = Field(default_factory=list)
    allow_credentials: bool = False
    allow_methods: list[str] = Field(default_factory=lambda: ["GET", "POST", "PUT", "DELETE"])
    allow_headers: list[str] = Field(default_factory=lambda: ["Authorization", "Content-Type"])
    max_age: int = 600


class CompressionConfig(_Section):
    enabled: bool = True
    minimum_size: int = 500  # bytes; don't waste CPU on tiny responses


class RateLimitConfig(_Section):
    enabled: bool = False  # opt-in: an unexpected 429 is worse than no limit
    # "<count>/<second|minute|hour>", parsed and validated by the plugin.
    default: str = "100/minute"
    by: Literal["ip"] = "ip"  # v0.2 keys on client IP; per-user/route land later


class ProdKitConfig(_Section):
    """Fully resolved, validated ProdKit configuration."""

    environment: Environment = "production"
    debug: bool = False
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    request_id: RequestIDConfig = Field(default_factory=RequestIDConfig)
    errors: ErrorsConfig = Field(default_factory=ErrorsConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    cors: CORSConfig = Field(default_factory=CORSConfig)
    compression: CompressionConfig = Field(default_factory=CompressionConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)


# Profile defaults: applied beneath toml/env/args. The one-liner must be
# pleasant in development and hardened in production.
_PROFILE_DEFAULTS: dict[Environment, dict[str, Any]] = {
    "development": {
        "debug": True,
        "logging": {"level": "DEBUG", "format": "console"},
        "security": {"hsts": False, "https_redirect": False},
        "errors": {"include_debug_details": True},
    },
    "staging": {
        "logging": {"format": "json"},
    },
    "production": {
        "debug": False,
        "logging": {"format": "json"},
        "security": {"hsts": True},
        "errors": {"include_debug_details": False},
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ProdKitConfigError(f"Invalid TOML in {path}: {exc}") from exc
    # Accept both flat sections and a [prodkit] table for top-level keys.
    prodkit_table = data.pop("prodkit", {})
    if not isinstance(prodkit_table, dict):
        raise ProdKitConfigError(f"[prodkit] in {path} must be a table")
    return _deep_merge(data, prodkit_table)


def _parse_env_value(raw: str) -> Any:
    lowered = raw.strip().lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    if "," in raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return raw


def _load_env(environ: dict[str, str]) -> dict[str, Any]:
    """PRODKIT_DEBUG=false → {"debug": False};
    PRODKIT_LOGGING__LEVEL=DEBUG → {"logging": {"level": "DEBUG"}}."""
    result: dict[str, Any] = {}
    for key, raw in environ.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        path = key[len(_ENV_PREFIX) :].lower().split("__")
        cursor = result
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
            if not isinstance(cursor, dict):
                raise ProdKitConfigError(f"Conflicting environment variable: {key}")
        cursor[path[-1]] = _parse_env_value(raw)
    return result


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["Invalid ProdKit configuration:"]
    for err in exc.errors():
        location = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"  - {location}: {err['msg']}")
    return "\n".join(lines)


def resolve_config(
    overrides: dict[str, Any] | None = None,
    *,
    toml_path: Path | str = "prodkit.toml",
    environ: dict[str, str] | None = None,
) -> ProdKitConfig:
    """Resolve configuration from all layers and validate it."""
    environ = dict(os.environ) if environ is None else environ
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}

    toml_layer = _load_toml(Path(toml_path))
    env_layer = _load_env(environ)

    # Environment must be decided first — it selects the profile defaults
    # that sit *under* every other layer.
    env_name = (
        overrides.get("environment")
        or env_layer.get("environment")
        or toml_layer.get("environment", "production")
    )
    if env_name not in _PROFILE_DEFAULTS:
        raise ProdKitConfigError(
            f"Unknown environment {env_name!r}; expected one of: "
            + ", ".join(sorted(_PROFILE_DEFAULTS))
        )

    merged = _PROFILE_DEFAULTS[env_name]
    for layer in (toml_layer, env_layer, overrides):
        merged = _deep_merge(merged, layer)
    merged["environment"] = env_name

    try:
        config = ProdKitConfig(**merged)
    except ValidationError as exc:
        raise ProdKitConfigError(_format_validation_error(exc)) from exc

    _check_production_safety(config)
    return config


def _check_production_safety(config: ProdKitConfig) -> None:
    """Refuse configurations that would silently weaken a production deployment."""
    if config.environment != "production":
        return
    problems: list[str] = []
    if config.debug:
        problems.append("debug=True is not allowed in production")
    if config.errors.include_debug_details:
        problems.append("errors.include_debug_details=True would leak tracebacks in production")
    if config.cors.enabled and config.cors.allow_credentials and "*" in config.cors.origins:
        problems.append(
            "cors: origins=['*'] with allow_credentials=True allows any site to make "
            "authenticated requests; list explicit origins instead"
        )
    if problems:
        raise ProdKitConfigError(
            "Unsafe production configuration:\n" + "\n".join(f"  - {p}" for p in problems)
        )
