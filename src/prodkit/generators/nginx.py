"""Nginx reverse-proxy generator: creates production-hardened nginx.conf."""

from __future__ import annotations

from pathlib import Path

from prodkit.generators.base import BaseGenerator, GeneratedFile, GeneratorContext

_NGINX_TEMPLATE = """\
# ==============================================================================
# Production Nginx reverse-proxy configuration for FastAPI + ProdKit
# ==============================================================================

upstream app_server {{
    server 127.0.0.1:{port};
    keepalive 32;
}}

server {{
    listen 80;
    server_name _;

    # Client limits
    client_max_body_size 20M;
    client_body_timeout 15s;
    client_header_timeout 15s;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_min_length 500;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/json
        application/javascript
        application/xml
        application/xml+rss
        image/svg+xml;

    # Proxy headers passed upstream to FastAPI
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Request-ID $request_id;
    proxy_set_header traceparent $http_traceparent;

    # Timeouts
    proxy_connect_timeout 10s;
    proxy_read_timeout 60s;
    proxy_send_timeout 60s;

    # Health check endpoints (bypass access logs)
    location {health_path} {{
        proxy_pass http://app_server;
        access_log off;
    }}

    location {live_path} {{
        proxy_pass http://app_server;
        access_log off;
    }}
{metrics_block}
    # Application routes
    location / {{
        proxy_pass http://app_server;
    }}
}}
"""


class NginxGenerator(BaseGenerator):
    """Generates a hardened Nginx reverse proxy configuration."""

    name = "nginx"
    description = "Generate a production-hardened Nginx reverse-proxy configuration"

    def generate(self, ctx: GeneratorContext) -> list[GeneratedFile]:
        metrics_block = ""
        if ctx.metrics_enabled:
            metrics_block = f"""
    # Metrics endpoint (restrict to internal scrapers/networks)
    location {ctx.metrics_path} {{
        proxy_pass http://app_server;
        # allow 10.0.0.0/8;
        # allow 127.0.0.1;
        # deny all;
    }}
"""

        content = _NGINX_TEMPLATE.format(
            port=ctx.port,
            health_path=ctx.health_path,
            live_path=ctx.live_path,
            metrics_block=metrics_block,
        )

        return [
            GeneratedFile(
                path=Path("nginx.conf"),
                content=content.strip() + "\n",
                description="Production Nginx reverse-proxy configuration",
            )
        ]
