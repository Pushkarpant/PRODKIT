"""Docker generator: creates hardened multi-stage Dockerfile and .dockerignore."""

from __future__ import annotations

from pathlib import Path

from prodkit.generators.base import BaseGenerator, GeneratedFile, GeneratorContext

_DOCKERFILE_TEMPLATE = """\
# ==============================================================================
# Multi-stage production Dockerfile for FastAPI with ProdKit
# ==============================================================================

# --- Stage 1: Build & dependencies ---
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies if needed
RUN apt-get update && \\
    apt-get install -y --no-install-recommends gcc libpq-dev && \\
    rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy dependency manifests first for layer caching
COPY pyproject.toml* requirements.txt* ./
RUN if [ -f requirements.txt ]; then \\
        pip install --no-cache-dir -r requirements.txt; \\
    elif [ -f pyproject.toml ]; then \\
        pip install --no-cache-dir .; \\
    fi

# --- Stage 2: Minimal runtime image ---
FROM python:3.12-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    PRODKIT_ENVIRONMENT=production \\
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Create a non-privileged user and group
RUN groupadd -g 10001 appgroup && \\
    useradd -u 10001 -g appgroup -s /bin/sh -d /app appuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application source
COPY --chown=appuser:appgroup . /app

# Switch to non-root user
USER appuser

# Expose application port
EXPOSE {port}

# Container healthcheck using standard library urllib
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \\
    CMD python -c \\
    "import urllib.request as r; r.urlopen('http://localhost:{port}{health_path}')" || exit 1

# Production server entrypoint
CMD ["uvicorn", "{app_spec}", "--host", "0.0.0.0", "--port", "{port}", "--workers", "4"]
"""

_DOCKERIGNORE_TEMPLATE = """\
# Git
.git
.gitignore

# Python bytecode & cache
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/
.coverage
.coverage.*
htmlcov/
.ruff_cache/
.mypy_cache/
.import_linter_cache/

# Virtual environments
.venv/
venv/
ENV/
env/

# Environment files with secrets
.env
.env.*
!.env.example

# Development & documentation
tests/
docs/
*.md
!README.md
.github/

# Docker assets
Dockerfile
.dockerignore
docker-compose*.yml
"""


class DockerGenerator(BaseGenerator):
    """Generates a hardened multi-stage Dockerfile and .dockerignore."""

    name = "docker"
    description = "Generate a multi-stage Dockerfile and .dockerignore"

    def generate(self, ctx: GeneratorContext) -> list[GeneratedFile]:
        dockerfile_content = _DOCKERFILE_TEMPLATE.format(
            port=ctx.port,
            health_path=ctx.health_path,
            app_spec=ctx.app_spec,
        )

        return [
            GeneratedFile(
                path=Path("Dockerfile"),
                content=dockerfile_content,
                description="Multi-stage, non-root production Dockerfile",
            ),
            GeneratedFile(
                path=Path(".dockerignore"),
                content=_DOCKERIGNORE_TEMPLATE,
                description="Docker build ignore file",
            ),
        ]
