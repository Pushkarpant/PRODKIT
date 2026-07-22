"""Security plugin: response security headers, trusted hosts, HTTPS redirect.

Headers follow current OWASP Secure Headers recommendations. CSP is opt-in
because a wrong default CSP breaks apps; everything else is safe universally.
"""

from __future__ import annotations

from typing import ClassVar

from starlette.datastructures import MutableHeaders
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from prodkit.contracts.plugin import PRIORITY_SECURITY, Audit, Plugin
from prodkit.core.context import Context


class SecurityHeadersMiddleware:
    """Pure-ASGI middleware (no BaseHTTPMiddleware overhead) that stamps
    security headers on every response."""

    def __init__(self, app: ASGIApp, headers: dict[str, str]) -> None:
        self.app = app
        self.headers = headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.headers.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def build_security_headers(ctx: Context) -> dict[str, str]:
    cfg = ctx.config.security
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": cfg.frame_options,
        "Referrer-Policy": cfg.referrer_policy,
        "Permissions-Policy": cfg.permissions_policy,
        # Kill legacy XSS auditor behavior explicitly (OWASP recommendation).
        "X-XSS-Protection": "0",
    }
    if cfg.hsts:
        headers["Strict-Transport-Security"] = f"max-age={cfg.hsts_max_age}; includeSubDomains"
    if cfg.content_security_policy:
        headers["Content-Security-Policy"] = cfg.content_security_policy
    return headers


class SecurityPlugin(Plugin):
    name: ClassVar[str] = "security"

    def register_middleware(self, ctx: Context) -> None:
        cfg = ctx.config.security
        ctx.add_middleware(
            SecurityHeadersMiddleware,
            priority=PRIORITY_SECURITY,
            headers=build_security_headers(ctx),
        )
        if cfg.trusted_hosts:
            # Slightly outside the headers middleware: reject bad hosts early.
            ctx.add_middleware(
                TrustedHostMiddleware,
                priority=PRIORITY_SECURITY - 10,
                allowed_hosts=cfg.trusted_hosts,
            )
        if cfg.https_redirect:
            ctx.add_middleware(HTTPSRedirectMiddleware, priority=PRIORITY_SECURITY - 20)

    def doctor(self, ctx: Context) -> list[Audit]:
        cfg = ctx.config.security
        is_prod = ctx.config.environment == "production"
        audits = [
            Audit(
                name="Security headers",
                status="ok",
                detail="nosniff, X-Frame-Options, Referrer-Policy, Permissions-Policy",
                weight=15,
            ),
            Audit(
                name="HSTS",
                status="ok" if cfg.hsts else ("warn" if is_prod else "ok"),
                detail="enabled" if cfg.hsts else "disabled",
                recommendation=(
                    "enable HSTS in production once served over HTTPS"
                    if (is_prod and not cfg.hsts)
                    else ""
                ),
                weight=10,
            ),
            Audit(
                name="Content-Security-Policy",
                status="ok" if cfg.content_security_policy else "warn",
                detail="set" if cfg.content_security_policy else "not set",
                recommendation=(
                    ""
                    if cfg.content_security_policy
                    else "set security.content_security_policy to mitigate XSS/injection"
                ),
                weight=10,
            ),
            Audit(
                name="Trusted hosts",
                status="ok" if cfg.trusted_hosts else "warn",
                detail=", ".join(cfg.trusted_hosts) if cfg.trusted_hosts else "not restricted",
                recommendation=(
                    ""
                    if cfg.trusted_hosts
                    else "set security.trusted_hosts to block Host-header spoofing"
                ),
                weight=8,
            ),
        ]
        return audits
