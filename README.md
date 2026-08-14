<div align="center">

# ⚡ ProdKit

### *One line. Production ready.*

The production engine for **[FastAPI](https://fastapi.tiangolo.com/)**.

```python
from fastapi import FastAPI
from prodkit import Production

app = FastAPI()
Production(app)  # 👈 That's it. Production hardened.
```

[![PyPI Version](https://img.shields.io/pypi/v/prodkit.svg?style=for-the-badge&color=blue)](https://pypi.org/project/prodkit/)
[![Python Versions](https://img.shields.io/pypi/pyversions/prodkit.svg?style=for-the-badge&color=snake)](https://pypi.org/project/prodkit/)
[![Build Status](https://img.shields.io/github/actions/workflow/status/Pushkarpant/PRODKIT/ci.yml?branch=main&style=for-the-badge&label=CI)](https://github.com/Pushkarpant/PRODKIT/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://github.com/Pushkarpant/PRODKIT/blob/main/LICENSE)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg?style=for-the-badge)](https://github.com/astral-sh/ruff)

[⚡ Quick Start](#-quick-start) · [📦 Installation](#-installation) · [✨ What You Get](#-what-you-get) · [🩺 CLI Doctor](#-cli--prodkit-doctor) · [🎛️ Configuration](#-configuration) · [🔌 Plugins](#-writing-a-plugin) · [🗺️ Roadmap](#-project-status--roadmap)

---

</div>

<br/>

## 🎯 The Problem & Solution

<details open>
<summary><b>💡 Why does ProdKit exist? (Click to toggle comparison)</b></summary>

<br/>

Every FastAPI service that goes to production re-implements the exact same **~500 lines of glue code**: security headers, JSON access logs, request-ID correlation, RFC 9457 error normalization, Kubernetes health probes, CORS safety, and rate-limiting. 

FastAPI is a micro-framework and deliberately omits this. **ProdKit provides the production batteries in a single import.**

| Without ProdKit ❌ | With ProdKit (`Production(app)`) ✅ |
|---|---|
| 🔴 Plain error 500s leak python stack traces to clients | 🛡️ RFC 9457 `problem+json` — 500s opaque to users, traced in logs |
| 🔴 Ad-hoc log lines without correlation IDs | 📋 Structured JSON logs with auto-injected `X-Request-ID` |
| 🔴 Missing security headers (vulnerable to clickjacking/sniffing) | 🔒 OWASP-hardened headers (`nosniff`, `DENY`, HSTS, CSP) |
| 🔴 Wildcard CORS combined with credentials footgun | 🚫 Refuses unsafe prod configs at startup with named key error |
| 🔴 Hand-rolled `/health` endpoints that don't check dependencies | 🏥 Native `/health`, `/live`, and `/ready` with dependency checks |
| 🔴 Hard to update when security standards evolve | 🔄 `pip install -U prodkit` upgrades all your apps in seconds |

</details>

---

## 💻 Interactive Demo

### 1️⃣ Run Your App
```python
# main.py
from fastapi import FastAPI
from prodkit import Production

app = FastAPI(title="Payment Service")
Production(app)  # Auto-configures production profile


@app.get("/charge")
def charge():
    return {"status": "success"}
```

```bash
uvicorn main:app
```

### 2️⃣ Inspect Production Headers & Request Tracing

<details open>
<summary><b>🔍 <code>curl -i http://localhost:8000/charge</code> (Click to inspect output)</b></summary>

```http
HTTP/1.1 200 OK
content-type: application/json
x-request-id: 26fdc49565614c2a9ef1a3b8d4e0f712
x-content-type-options: nosniff
x-frame-options: DENY
strict-transport-security: max-age=63072000; includeSubDomains
referrer-policy: strict-origin-when-cross-origin
permissions-policy: camera=(), microphone=(), geolocation=()
x-xss-protection: 0

{"status":"success"}
```
</details>

<details>
<summary><b>🏥 <code>curl -i http://localhost:8000/ready</code> (Kubernetes Readiness Check)</b></summary>

```http
HTTP/1.1 200 OK
content-type: application/json

{
  "status": "ready",
  "checks": [
    { "name": "request-id", "passed": true },
    { "name": "logging", "passed": true },
    { "name": "security", "passed": true }
  ]
}
```
</details>

---

## 📦 Installation

```bash
# Base framework (zero extra dependencies)
pip install prodkit

# Recommended extras
pip install "prodkit[cli]"       # Includes `prodkit doctor` CLI (typer + rich)
pip install "prodkit[metrics]"   # Prometheus /metrics endpoint
pip install "prodkit[otel]"      # OpenTelemetry tracing
pip install "prodkit[redis]"     # Distributed Redis rate-limiting & cache
pip install "prodkit[all]"       # All available plugins and extras
```

| Extra | Adds | Dependencies |
|---|---|---|
| `cli` | `prodkit doctor`, `inspect`, `init` commands | `typer`, `rich` |
| `metrics` | Prometheus metrics endpoint (`/metrics`) | `prometheus-client` |
| `otel` | W3C distributed tracing with OpenTelemetry | `opentelemetry-api`, `opentelemetry-sdk` |
| `redis` | Multi-worker rate limiting & distributed cache | `redis` / `fakeredis` |
| `brotli` | High-ratio Brotli response compression | `brotli` |
| `all` | Everything above | All optional extras |

---

## ✨ What You Get Out of the Box

ProdKit includes **11 modular built-in plugins**, organized with explicit middleware execution priorities:

```
  100  RequestID          (Outer-most: generates/extracts X-Request-ID)
  200  Structured Logging (Correlates log lines with Request ID & timing)
  290  OpenTelemetry      (Request tracing spans & W3C context propagation)
  300  Prometheus Metrics (Exposes /metrics with route-template labels)
  400  Security Headers   (OWASP nosniff, HSTS, X-Frame-Options, CSP)
  500  CORS Safety        (Strict origin validation, refuses wildcard+creds)
  600  Rate Limiting      (Per-IP window limits, memory or Redis backend)
  700  Compression        (Gzip & Brotli response compression)
       [ Your FastAPI App Code ]
```

<details>
<summary><b>📖 Expand Complete Feature Matrix</b></summary>

<br/>

| Icon | Feature | Description | Default |
|:---:|---|---|:---:|
| 🆔 | **Request IDs** | `X-Request-ID` attached to every response, bound to async context for log correlation. | `On` |
| 📋 | **Structured Logging** | Production JSON logs (Datadog/CloudWatch/Loki ready) or colorful console logs in dev. | `On` |
| 🛡️ | **Security Headers** | `nosniff`, `X-Frame-Options: DENY`, `Strict-Transport-Security`, `Referrer-Policy`. | `On` |
| 🚨 | **Error Normalization** | [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) `problem+json` standard. 500 tracebacks hidden in prod. | `On` |
| ❤️ | **Health Probes** | K8s endpoints: `/health` (liveness), `/live`, and `/ready` (aggregates plugin checks). | `On` |
| 🌐 | **CORS Guard** | Prevents insecure wildcard credentials (`origins=["*"]` + `credentials=True` fails boot). | `Configured` |
| 📦 | **Compression** | Automatic Gzip (and optional Brotli) compression for payloads > 500 bytes. | `On` |
| 🚦 | **Rate Limiting** | Per-IP sliding limits (`100/minute`), returns `429 Too Many Requests` with `Retry-After`. | `Opt-in` |
| 📊 | **Prometheus Metrics** | Scrapeable `/metrics` endpoint (request totals, duration histograms, in-flight gauges). | `Opt-in` |
| 🗄️ | **Cache Service** | Injection-ready cache (`MemoryCache` or `RedisCache`) registered in app context. | `Opt-in` |
| 🔭 | **OpenTelemetry** | Auto-instrumentation of HTTP requests with OTLP/Console exporters & W3C headers. | `Opt-in` |

</details>

---

## 🩺 CLI — `prodkit doctor`

Run static & runtime security audits against your app and get a **0–100 Production Score**:

```bash
prodkit doctor --app main:app
```

```text
                     Production Readiness Audit
   ┌───┬────────────────────────┬─────────────────────┬──────────────────────────┐
   │ ✔ │ Security headers       │ nosniff, X-Frame... │                          │
   │ ✔ │ Structured logging     │ json @ INFO         │                          │
   │ ✔ │ Error normalization    │ 500s opaque         │                          │
   │ ✔ │ Request IDs            │ enabled (header)    │                          │
   │ ✔ │ Health probes          │ /health /ready      │                          │
   │ ⚠ │ Rate limiting          │ memory backend      │ set backend="redis" ...  │
   │ ⚠ │ Content-Security-Policy│ default-src missing │ set CSP for web apps     │
   └───┴────────────────────────┴─────────────────────┴──────────────────────────┘
   Production Score: 88 / 100   [ 2 Warning(s) ]
```

### 🚦 Gate CI/CD Builds
Enforce production standards in GitHub Actions or GitLab CI:

```bash
# Fails CI build (exit code 1) if production readiness score falls below threshold
prodkit doctor --app main:app --strict --min-score 90
```

<details>
<summary><b>🛠️ More CLI Commands (<code>inspect</code>, <code>plugins</code>, <code>init</code>)</b></summary>

<br/>

```bash
# View resolved configuration, active plugins, and middleware execution stack:
prodkit inspect --app main:app

# List all active plugins and their implemented lifecycle hooks:
prodkit plugins --app main:app

# Scaffold starter prodkit.toml configuration file:
prodkit init --example
```

</details>

---

## 🎛️ Configuration

ProdKit merges configuration across **4 priority layers** (highest wins):

$$\text{Python Args} \longrightarrow \text{Environment Vars} \longrightarrow \text{\texttt{prodkit.toml}} \longrightarrow \text{Profile Defaults}$$

<details open>
<summary><b>⚙️ Choose Configuration Style (Click to tab)</b></summary>

#### Option A: Python Arguments
```python
Production(
    app,
    environment="production",
    cors={"origins": ["https://app.example.com"]},
    rate_limit={"default": "100/minute", "backend": "redis"},
    metrics=True,
    tracing={"exporter": "otlp", "sample_rate": 0.2},
)
```

#### Option B: `prodkit.toml`
```toml
[prodkit]
environment = "production"

[logging]
level = "INFO"
format = "json"

[rate_limit]
enabled = true
default = "100/minute"
backend = "redis"

[metrics]
enabled = true
path = "/metrics"
```

#### Option C: Environment Variables (`__` for nested keys)
```bash
export PRODKIT_ENVIRONMENT=production
export PRODKIT_LOGGING__LEVEL=WARNING
export PRODKIT_RATE_LIMIT__BACKEND=redis
export PRODKIT_METRICS__ENABLED=true
```

</details>

---

## 🔌 Writing a Custom Plugin

All features in ProdKit (including built-ins) are plugins implementing the `Plugin` contract.

```python
from prodkit import Plugin, Check, Audit, Production


class DatabaseHealthPlugin(Plugin):
    name = "db-health"
    requires = []  # Dependency ordering

    async def startup(self, ctx):
        # Async resource setup
        ctx.registry.provide("db_pool", await connect_db())

    async def shutdown(self, ctx):
        pool = ctx.registry.get("db_pool")
        await pool.close()

    def checks(self, ctx):
        # Feeds into K8s /ready probe
        is_connected = ctx.registry.get("db_pool").is_active()
        return [Check(name="database", passed=is_connected)]

    def doctor(self, ctx):
        # Feeds into `prodkit doctor` score
        return [Audit(name="Database Connection", status="ok", detail="Pool initialized")]


Production(app, plugins=[DatabaseHealthPlugin()])
```

---

## 🛡️ Plays Nice With Your App

- **Zero Lock-in**: Mutates/wraps the FastAPI instance. Remove `Production(app)` anytime to return to plain FastAPI.
- **Lifespan Composition**: Your custom `@asynccontextmanager` lifespan is preserved and wrapped (Plugin startup $\to$ App lifespan $\to$ Plugin shutdown).
- **Your Code Wins**: If your route explicitly sets a header or error handler, your application code takes precedence.

---

## 🗺️ Project Status & Roadmap

| Version | Status | Highlights |
|---|---|---|
| **v0.1.0** | ✅ Released | Core kernel, security headers, JSON logs, RFC 9457 error normalization, `/health` |
| **v0.2.0** | ✅ Released | `prodkit doctor` CLI, readiness score, in-memory rate limiting |
| **v0.3.0** | ✅ **Current** | **Prometheus metrics, Redis backends, OpenTelemetry tracing, Cache service** |
| **v0.4.0** | 🚧 Next | `prodkit generate` (Dockerfile, nginx, docker-compose, GitHub Actions CI) |
| **v0.5.0** | 📅 Planned | Public Plugin SDK & Ecosystem (`prodkit-sentry`, entry-point discovery) |
| **v1.0.0** | 🎯 Milestone | Frozen Public API, LTS release, Production case studies |

---

## 🤝 Contributing & License

We welcome contributions! Please see [CONTRIBUTING.md](https://github.com/Pushkarpant/PRODKIT/blob/main/CONTRIBUTING.md) and [SECURITY.md](https://github.com/Pushkarpant/PRODKIT/blob/main/SECURITY.md).

```bash
git clone https://github.com/Pushkarpant/PRODKIT.git
cd PRODKIT
python -m venv .venv && source .venv/bin/activate  # on Windows: .venv\Scripts\activate
pip install -e ".[dev,all]"
pytest
```

Distributed under the **[MIT License](https://github.com/Pushkarpant/PRODKIT/blob/main/LICENSE)**.

<br/>

<div align="center">

**Built with ❤️ by [Pushkar Pant](https://github.com/Pushkarpant)**

*FastAPI builds APIs. ProdKit makes them production-ready.*

</div>
