# ProdKit

> **One line. Production ready.**

The production framework for [FastAPI](https://fastapi.tiangolo.com/).

```python
from fastapi import FastAPI
from prodkit import Production

app = FastAPI()
Production(app)
```

That's it. Your app now has security headers, structured JSON logging with
request-ID correlation, RFC 9457 error responses, Kubernetes-ready health
endpoints, and gzip compression — configured to current best practice,
hardened for production, and pleasant in development.

[![CI](https://github.com/Pushkarpant/PRODKIT/actions/workflows/ci.yml/badge.svg)](https://github.com/Pushkarpant/PRODKIT/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/Pushkarpant/PRODKIT/blob/main/LICENSE)

---

## Why

Every production FastAPI service re-implements the same ~500 lines of glue:
middleware ordering, security headers, structured logging, health checks,
error normalization, graceful shutdown. FastAPI deliberately doesn't ship
this — it's a micro framework. **ProdKit is the batteries.**

And unlike a project template, ProdKit is a library: when best practices
evolve, `pip install -U prodkit` updates every app you own.

## Installation

[**`pip install prodkit`**](https://pypi.org/project/prodkit/)

```bash
pip install prodkit
```

Requires Python 3.10+ and FastAPI 0.110+. The base install depends only on
FastAPI and Pydantic — nothing else.

## Quick Start

```python
from fastapi import FastAPI
from prodkit import Production

app = FastAPI()
Production(app)                      # production profile by default

@app.get("/hello")
def hello():
    return {"message": "hello"}
```

```bash
uvicorn main:app
```

```text
$ curl -i localhost:8000/hello
HTTP/1.1 200 OK
x-request-id: 26fdc49565614c2a9ef1a3b8d4e0f712
x-content-type-options: nosniff
x-frame-options: DENY
strict-transport-security: max-age=63072000; includeSubDomains
referrer-policy: strict-origin-when-cross-origin
...
```

For local development, flip the profile — pretty console logs, debug error
details, no HSTS:

```python
Production(app, environment="development")
```

## What You Get

| Feature | Details |
|---|---|
| 🆔 **Request IDs** | `X-Request-ID` on every response, propagated into every log line. Inbound IDs untrusted by default. |
| 📋 **Structured logging** | One JSON object per request in production (Datadog/Loki/CloudWatch-ready); pretty console logs in development. |
| 🛡️ **Security headers** | OWASP-aligned: `nosniff`, `X-Frame-Options`, HSTS, `Referrer-Policy`, `Permissions-Policy`. Your own headers always win. |
| 🚨 **Error normalization** | [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) `problem+json` responses. Unhandled 500s are **opaque to clients** — the traceback goes to logs, correlated by request ID. |
| ❤️ **Health endpoints** | `/health`, `/live` (liveness) and `/ready` (readiness — aggregates checks from every plugin, 503 until all pass). Kubernetes-native. |
| 🌐 **CORS** | Explicit origins only; the wildcard-with-credentials footgun is refused at boot. |
| 📦 **Compression** | Gzip for responses over 500 bytes. |
| 🔌 **Plugin system** | Every feature above is a plugin. Write your own with 6 optional hooks. |

## Configuration

Everything is configurable through four layers (highest wins):

```
Python args  >  environment variables  >  prodkit.toml  >  profile defaults
```

**Python:**

```python
Production(
    app,
    environment="production",
    cors={"origins": ["https://app.example.com"]},   # dict = configure & enable
    compression=False,                                # bool = toggle
    security={"trusted_hosts": ["api.example.com"]},
)
```

**Environment variables** (`__` descends into sections):

```bash
PRODKIT_ENVIRONMENT=production
PRODKIT_LOGGING__LEVEL=WARNING
PRODKIT_SECURITY__TRUSTED_HOSTS=api.example.com,admin.example.com
```

**`prodkit.toml`:**

```toml
[prodkit]
environment = "production"

[logging]
level = "INFO"

[cors]
enabled = true
origins = ["https://app.example.com"]
```

### Fail-fast, refuse-unsafe

Misconfiguration fails **at startup with a named key**, never silently:

```text
ProdKitConfigError: Invalid ProdKit configuration:
  - logging.levle: Extra inputs are not permitted
```

And configurations that would weaken a production deployment are refused,
not warned about:

- `debug=True` in production
- error responses that would leak tracebacks in production
- CORS `origins=["*"]` combined with `allow_credentials=True`

## Writing a Plugin

```python
from prodkit import Check, Plugin, Production

class DatabasePlugin(Plugin):
    name = "database"

    async def startup(self, ctx):
        self.pool = await create_pool(...)
        ctx.registry.provide("db", self.pool)

    async def shutdown(self, ctx):
        await self.pool.close()

    def checks(self, ctx):
        return [Check(name="database", passed=self.pool.is_alive())]

Production(app, plugins=[DatabasePlugin()])
```

Your check now shows up in `/ready` automatically. Plugins can declare
`requires = ("other-plugin",)` and the kernel activates them in dependency
order — cycles and missing dependencies fail at boot.

Middleware registered by plugins carries an explicit integer priority, so
the middleware onion is always correctly ordered no matter what order
plugins load in (request-id outermost, compression innermost).

## Plays Nice With Your App

- **Same app object.** Routes, dependencies, and existing middleware keep
  working. Remove `Production(app)` and you have a plain FastAPI app again.
- **Your lifespan survives.** ProdKit *composes* with an existing `lifespan`:
  plugin startup → your lifespan → plugin shutdown (LIFO).
- **Your headers win.** Security headers use set-if-absent semantics.
- **Every feature can be turned off.** `Production(app, security=False, ...)`

## Project Status

**v0.1.0 — alpha.** Core kernel and seven built-in plugins, 60 tests, 98%
coverage, strict mypy, CI across Python 3.10–3.13.

Roadmap: `prodkit doctor` CLI with a production-readiness score (v0.2),
Prometheus metrics + Redis backends (v0.3), Dockerfile/nginx/CI generators
(v0.4), public plugin SDK (v0.5), auth helpers (v0.6), stable API (v1.0).
Full details in [docs/ARCHITECTURE.md](https://github.com/Pushkarpant/PRODKIT/blob/main/docs/ARCHITECTURE.md).

## Contributing

Contributions welcome — see [CONTRIBUTING.md](https://github.com/Pushkarpant/PRODKIT/blob/main/CONTRIBUTING.md).
Security reports: see [SECURITY.md](https://github.com/Pushkarpant/PRODKIT/blob/main/SECURITY.md) (never open a public issue).

```bash
git clone https://github.com/Pushkarpant/PRODKIT
cd PRODKIT
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## License

[MIT](https://github.com/Pushkarpant/PRODKIT/blob/main/LICENSE)

## Author

**[Pushkar Pant](https://github.com/Pushkarpant)** — [pantpushkar4@gmail.com](mailto:pantpushkar4@gmail.com)

---

*FastAPI builds APIs. ProdKit makes them production-ready.*
