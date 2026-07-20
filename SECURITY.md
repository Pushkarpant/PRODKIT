# Security Policy

ProdKit's purpose is making FastAPI applications production-ready, so we treat
security reports with the highest priority.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✔         |

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

Report privately via GitHub Security Advisories:
https://github.com/Pushkarpant/PRODKIT/security/advisories/new

You will receive an acknowledgement within 48 hours and a status update within
7 days. We follow coordinated disclosure: we will work with you on a fix and
credit you in the advisory unless you prefer otherwise.

## Scope

In scope:
- Any way ProdKit weakens the security of an application it is added to
- Header injection, log injection, information disclosure in error responses
- Bypasses of security defaults (trusted hosts, HTTPS redirect, headers)
- Supply-chain concerns with our release process

Out of scope:
- Vulnerabilities in FastAPI/Starlette/Pydantic themselves (report upstream)
- Applications misconfiguring ProdKit against documented warnings

## Release Integrity

- Releases are published to PyPI via GitHub Actions **Trusted Publishing**
  (OIDC) — no long-lived PyPI tokens exist.
- All dependencies are minimal by design: the base install depends only on
  `fastapi`, `pydantic`, and `pydantic-settings`.
