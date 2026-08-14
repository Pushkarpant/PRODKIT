"""Docker Compose generator: creates production-ready docker-compose.yml."""

from __future__ import annotations

from pathlib import Path

from prodkit.generators.base import BaseGenerator, GeneratedFile, GeneratorContext


class ComposeGenerator(BaseGenerator):
    """Generates docker-compose.yml with app service and optional Redis dependencies."""

    name = "compose"
    description = "Generate a production-ready docker-compose.yml"

    def generate(self, ctx: GeneratorContext) -> list[GeneratedFile]:
        app_env_entries = [
            "      - PRODKIT_ENVIRONMENT=production",
            f"      - PORT={ctx.port}",
        ]

        redis_service = ""
        volumes_section = ""
        depends_on_section = ""

        if ctx.has_redis:
            app_env_entries.extend(
                [
                    "      - PRODKIT_RATE_LIMIT__REDIS_URL=redis://redis:6379/0",
                    "      - PRODKIT_CACHE__REDIS_URL=redis://redis:6379/0",
                ]
            )
            depends_on_section = """\
    depends_on:
      redis:
        condition: service_healthy
"""
            redis_service = """\
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3
"""
            volumes_section = """\
volumes:
  redis_data:
"""

        env_block = "\n".join(app_env_entries)

        compose_content = f"""\
# ==============================================================================
# Docker Compose configuration for FastAPI + ProdKit
# ==============================================================================

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    ports:
      - "${{PORT:-{ctx.port}}}:{ctx.port}"
    environment:
{env_block}
    env_file:
      - path: .env
        required: false
{depends_on_section}    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:{ctx.port}{ctx.health_path}')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

{redis_service}{volumes_section}
networks:
  default:
    name: prodkit_net
"""
        return [
            GeneratedFile(
                path=Path("docker-compose.yml"),
                content=compose_content.strip() + "\n",
                description="Docker Compose multi-service deployment definition",
            )
        ]
