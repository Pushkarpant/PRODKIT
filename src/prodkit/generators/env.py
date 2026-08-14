"""Environment variable generator: creates .env.example with all configuration options."""

from __future__ import annotations

from pathlib import Path

from prodkit.generators.base import BaseGenerator, GeneratedFile, GeneratorContext

_ENV_TEMPLATE = """\
# ==============================================================================
# ProdKit Environment Configuration Template (.env.example)
#
# Resolution priority: Python arguments > Environment variables > prodkit.toml > defaults
# Format: PRODKIT_<SECTION>__<KEY> or PRODKIT_<KEY> for root options.
# ==============================================================================

# Core environment: development | staging | production
PRODKIT_ENVIRONMENT=production
PRODKIT_DEBUG=false

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------
PRODKIT_LOGGING__ENABLED=true
PRODKIT_LOGGING__LEVEL=INFO
PRODKIT_LOGGING__FORMAT=json
PRODKIT_LOGGING__INCLUDE_REQUEST_BODY=false

# ------------------------------------------------------------------------------
# Request ID
# ------------------------------------------------------------------------------
PRODKIT_REQUEST_ID__ENABLED=true
PRODKIT_REQUEST_ID__HEADER=X-Request-ID
PRODKIT_REQUEST_ID__TRUST_INCOMING=false

# ------------------------------------------------------------------------------
# Error Handling (RFC 9457 Problem Details)
# ------------------------------------------------------------------------------
PRODKIT_ERRORS__ENABLED=true
PRODKIT_ERRORS__INCLUDE_DEBUG_DETAILS=false

# ------------------------------------------------------------------------------
# Health Checks
# ------------------------------------------------------------------------------
PRODKIT_HEALTH__ENABLED=true
PRODKIT_HEALTH__HEALTH_PATH=/health
PRODKIT_HEALTH__READY_PATH=/ready
PRODKIT_HEALTH__LIVE_PATH=/live

# ------------------------------------------------------------------------------
# Security Headers & TLS
# ------------------------------------------------------------------------------
PRODKIT_SECURITY__ENABLED=true
PRODKIT_SECURITY__HSTS=true
PRODKIT_SECURITY__HSTS_MAX_AGE=63072000
PRODKIT_SECURITY__FRAME_OPTIONS=DENY
PRODKIT_SECURITY__REFERRER_POLICY=strict-origin-when-cross-origin
PRODKIT_SECURITY__HTTPS_REDIRECT=false
# PRODKIT_SECURITY__TRUSTED_HOSTS=api.example.com,app.example.com
# PRODKIT_SECURITY__CONTENT_SECURITY_POLICY=default-src 'self'

# ------------------------------------------------------------------------------
# CORS
# ------------------------------------------------------------------------------
PRODKIT_CORS__ENABLED=false
# PRODKIT_CORS__ORIGINS=https://app.example.com,https://admin.example.com
PRODKIT_CORS__ALLOW_CREDENTIALS=false

# ------------------------------------------------------------------------------
# Compression (Gzip)
# ------------------------------------------------------------------------------
PRODKIT_COMPRESSION__ENABLED=true
PRODKIT_COMPRESSION__MINIMUM_SIZE=500

# ------------------------------------------------------------------------------
# Rate Limiting
# ------------------------------------------------------------------------------
PRODKIT_RATE_LIMIT__ENABLED=false
PRODKIT_RATE_LIMIT__DEFAULT=100/minute
PRODKIT_RATE_LIMIT__BACKEND=memory
PRODKIT_RATE_LIMIT__REDIS_URL=redis://localhost:6379/0

# ------------------------------------------------------------------------------
# Prometheus Metrics (requires prodkit[metrics])
# ------------------------------------------------------------------------------
PRODKIT_METRICS__ENABLED=false
PRODKIT_METRICS__PATH=/metrics

# ------------------------------------------------------------------------------
# Caching Service (Memory / Redis)
# ------------------------------------------------------------------------------
PRODKIT_CACHE__ENABLED=false
PRODKIT_CACHE__BACKEND=memory
PRODKIT_CACHE__REDIS_URL=redis://localhost:6379/0
PRODKIT_CACHE__DEFAULT_TTL=300

# ------------------------------------------------------------------------------
# OpenTelemetry Distributed Tracing (requires prodkit[otel])
# ------------------------------------------------------------------------------
PRODKIT_TRACING__ENABLED=false
PRODKIT_TRACING__EXPORTER=otlp
PRODKIT_TRACING__SAMPLE_RATE=1.0
# PRODKIT_TRACING__SERVICE_NAME=my-fastapi-service
# PRODKIT_TRACING__ENDPOINT=http://localhost:4317
"""


class EnvGenerator(BaseGenerator):
    """Generates a documented .env.example containing all ProdKit configuration variables."""

    name = "env"
    description = "Generate a documented .env.example with all ProdKit settings"

    def generate(self, ctx: GeneratorContext) -> list[GeneratedFile]:
        return [
            GeneratedFile(
                path=Path(".env.example"),
                content=_ENV_TEMPLATE,
                description="Environment variable configuration template",
            )
        ]
