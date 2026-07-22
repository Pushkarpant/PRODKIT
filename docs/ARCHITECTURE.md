# ProdKit

> **One line. Production ready.**

The production framework for FastAPI.

```python
from fastapi import FastAPI
from prodkit import Production

app = FastAPI()
Production(app)
```

ProdKit turns any FastAPI application into a production-ready service: structured
logging, security headers, health checks, request IDs, metrics, rate limiting,
auth helpers, and deployment file generation — all opinionated by default, all
configurable, all replaceable.

---

## Table of Contents

1. [Why ProdKit](#why-prodkit)
2. [Design Principles](#design-principles)
3. [Architecture](#architecture)
4. [The Plugin Contract](#the-plugin-contract)
5. [Configuration System](#configuration-system)
6. [Lifecycle](#lifecycle)
7. [Built-in Plugins](#built-in-plugins)
8. [CLI](#cli)
9. [Project Layout](#project-layout)
10. [Testing Strategy](#testing-strategy)
11. [CI/CD](#cicd)
12. [Roadmap](#roadmap)
13. [Coding Standards](#coding-standards)
14. [Success Metrics](#success-metrics)
15. [FAQ / Design Decisions](#faq--design-decisions)

---

## Why ProdKit

Every production FastAPI service re-implements the same ~500 lines of glue:
middleware ordering, CORS, security headers, structured logging with request
correlation, `/health` + `/ready` endpoints, exception normalization, metrics,
graceful shutdown. FastAPI deliberately doesn't ship this — it's a micro
framework. ProdKit is the batteries.

**ProdKit is not:** a web framework, an ORM, a template engine, or a FastAPI
replacement. It extends FastAPI and never hides it.

---

## Design Principles

1. **Zero boilerplate** — one call configures sane production defaults.
2. **Progressive disclosure** — the one-liner works; every layer beneath it is
   reachable and overridable. No magic you can't turn off.
3. **Everything is a plugin** — including the built-ins. The kernel never
   imports a plugin.
4. **Explicit over implicit failure** — misconfiguration fails at startup, not
   at request time. `prodkit doctor` catches the rest.
5. **Type safe** — full type hints, `py.typed` marker, strict mypy.
6. **Minimal core dependencies** — the base install depends only on FastAPI
   and Pydantic. Redis, Prometheus, JWT libs, etc. are optional extras
   (`pip install prodkit[redis]`).
7. **Stable APIs** — SemVer; breaking changes only in major releases; public
   API surface is explicitly documented and tested.

---

## Architecture

```
Developer code
    │
    ▼
FastAPI app ──► Production(app, config, plugins)
                    │
                    ▼
              ┌───────────┐
              │  Kernel   │  config · lifecycle · registry · DI · events
              └─────┬─────┘
                    │ loads, orders, wires
                    ▼
              ┌───────────┐
              │  Plugins  │  health · logging · security · cors · metrics ···
              └─────┬─────┘
                    │ register middleware, routes, dependencies, hooks
                    ▼
        Production-ready FastAPI app (same object, unchanged for your code)
```

### Kernel responsibilities (and nothing else)

| Component        | Module                    | Responsibility                                        |
|------------------|---------------------------|-------------------------------------------------------|
| Production       | `core/production.py`      | Public entrypoint; orchestrates the boot sequence      |
| Config           | `core/config.py`          | Layered config resolution (Pydantic Settings)          |
| Plugin manager   | `core/plugin_manager.py`  | Discovery, dependency resolution, ordered activation   |
| Registry         | `core/registry.py`        | Named service registry (e.g. `"cache"`, `"logger"`)    |
| Context          | `core/context.py`         | The object handed to every plugin: config + registry + app |
| Lifecycle        | `core/lifecycle.py`       | Startup/shutdown orchestration via FastAPI lifespan    |
| Event bus        | `core/event_bus.py`       | In-process pub/sub for cross-plugin signals            |
| Exceptions       | `core/exceptions.py`      | `ProdKitError` hierarchy; standardized error responses |

**Rule: the kernel has zero imports from `prodkit.plugins`.** Enforced by an
import-linter contract in CI.

### Key architectural decisions

These refine the original spec — each solves a problem that would otherwise
surface in v0.2+:

**1. Middleware ordering is explicit, not registration-order.**
Starlette middleware is an onion: last-added runs first. Ad-hoc ordering breaks
things silently (e.g. request-ID middleware must wrap logging, CORS must sit
outside auth). Every middleware registration carries an integer `priority`;
the kernel sorts before applying. Built-ins ship with documented priorities:

```
 100  RequestID        (outermost — everything below sees the ID)
 200  Logging
 300  Metrics
 400  Security headers
 500  CORS
 600  Rate limiting
 700  Compression
 800  Auth
 (your app)
```

**2. Plugin hooks are async and receive the context.**
A sync `startup(self)` signature can't await a Redis connection. The contract
below uses async hooks with an explicit `Context` parameter.

**3. Plugins declare dependencies and the kernel topo-sorts them.**
`RateLimitPlugin` needs the cache backend; `MetricsPlugin` may consume logging
events. `requires: list[str]` on the plugin + topological sort in the plugin
manager = deterministic activation order and a clear startup error on cycles
or missing deps (instead of a `KeyError` at request time).

**4. Lifespan composition, not replacement.**
FastAPI apps often already have a `lifespan`. `Production(app)` wraps the
existing lifespan rather than overwriting it: ProdKit startup runs first,
user lifespan runs inside, ProdKit shutdown runs last (LIFO).

**5. Environment profiles.**
`environment: "development" | "staging" | "production"` changes defaults
(e.g. HTTPS redirect and trusted hosts off in dev, pretty logs in dev / JSON
in prod). This is the single biggest DX win — the one-liner must not make
local development painful, or nobody adopts it.

**6. Fail-fast config validation.**
All plugin configs are Pydantic models validated at boot. A typo'd
`PRODKIT_LOG_LEVLE` env var produces a startup warning from `doctor`-style
"unknown key" detection.

---

## The Plugin Contract

```python
# prodkit/contracts/plugin.py
from prodkit.core.context import Context

class Plugin:
    """Base class for all ProdKit plugins. All hooks are optional."""

    name: str                      # unique, kebab-case: "rate-limit"
    requires: list[str] = []      # names of plugins that must activate first

    def configure(self, ctx: Context) -> None:
        """Validate/resolve config. Runs first, in dependency order.
        Raise ProdKitConfigError to abort boot with a clear message."""

    def register_middleware(self, ctx: Context) -> None:
        """Call ctx.add_middleware(cls, priority=N, **options)."""

    def register_routes(self, ctx: Context) -> None:
        """Add routes via ctx.app (e.g. /health, /metrics)."""

    async def startup(self, ctx: Context) -> None:
        """Async resource acquisition (DB pools, Redis connections)."""

    async def shutdown(self, ctx: Context) -> None:
        """Graceful release. Runs in reverse activation order (LIFO)."""

    def doctor(self, ctx: Context) -> list[Check]:
        """Return health/readiness checks for `prodkit doctor`."""
```

The `Context` gives plugins everything they may touch:

```python
class Context:
    app: FastAPI                # the user's app
    config: ProdKitConfig       # fully resolved, typed config
    registry: Registry          # get/provide named services
    events: EventBus            # subscribe/emit cross-plugin events

    def add_middleware(self, cls, *, priority: int, **options): ...
```

**Third-party plugins** are discovered via the `prodkit.plugins` entry-point
group, so `pip install prodkit-sentry` + one config line activates it. Explicit
`plugins=[...]` always wins over discovery.

---

## Configuration System

Built on `pydantic-settings`. Resolution priority (highest wins):

```
1. Python arguments        Production(app, log_level="DEBUG")
2. Environment variables   PRODKIT_LOG_LEVEL=DEBUG
3. prodkit.toml            [logging] level = "DEBUG"
4. Profile defaults        (per environment: development/staging/production)
5. Library defaults
```

```toml
# prodkit.toml
[prodkit]
environment = "production"

[logging]
level = "INFO"
format = "json"          # "json" | "console"

[security]
hsts = true
trusted_hosts = ["api.example.com"]

[cors]
origins = ["https://app.example.com"]

[rate_limit]
enabled = true
default = "100/minute"
```

Feature toggles at the top level, full config in sections:

```python
Production(
    app,
    logging=True,          # bool toggles
    security=True,
    cors=CORSConfig(origins=["https://app.example.com"]),  # or typed config
    plugins=[MyCustomPlugin()],
)
```

Every plugin owns a Pydantic config model; the kernel composes them into one
validated `ProdKitConfig`. Unknown keys raise warnings; invalid values raise
`ProdKitConfigError` at boot.

---

## Lifecycle

```
Production(app) called
  ├─ 1. Resolve config (args > env > toml > profile > defaults)
  ├─ 2. Discover & collect plugins (built-ins + entry points + explicit)
  ├─ 3. Topo-sort by `requires`; fail on cycles/missing deps
  ├─ 4. configure(ctx) for each plugin, in order
  ├─ 5. Collect middleware registrations; sort by priority; apply
  ├─ 6. register_routes(ctx) for each plugin
  └─ 7. Wrap app lifespan
App serves
  ├─ lifespan enter: plugin startup() in order → user lifespan enter
  ├─ ... requests ...
  └─ lifespan exit: user lifespan exit → plugin shutdown() in REVERSE order
```

Startup failures abort boot with a single clear error naming the plugin and
the config key at fault — never a stack trace soup.

---

## Built-in Plugins

| Plugin        | Provides                                                          | Default    |
|---------------|-------------------------------------------------------------------|------------|
| `request-id`  | `X-Request-ID` generation/propagation, contextvar for logging     | on         |
| `logging`     | Structured logs (JSON in prod, pretty in dev), request/response timing, request-ID correlation | on |
| `errors`      | Normalized error responses ([RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem+json), safe 500s (no leaked tracebacks in prod) | on |
| `health`      | `/health` (liveness), `/ready` (readiness, aggregates plugin `doctor()` checks) | on |
| `security`    | Security headers (HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, CSP opt-in), trusted hosts, HTTPS redirect (prod profile only) | on |
| `cors`        | CORS with explicit origins (no wildcard-with-credentials footgun) | on if configured |
| `compression` | Gzip always; Brotli if `brotli` extra installed                   | on         |
| `metrics`     | Prometheus `/metrics`: request count/latency/in-flight, per-route labels | extra: `[metrics]` |
| `rate-limit`  | Per-IP / per-user / per-route; in-memory backend by default, Redis backend via `[redis]` | off |
| `cache`       | Cache service in registry; in-memory or Redis backend             | off        |
| `auth`        | JWT validation, API-key dependency, OAuth2 helpers — as FastAPI dependencies you opt routes into | extra: `[auth]` |

Notes:

- **Health endpoints**: `/health` returns 200 if the process is alive.
  `/ready` runs registered checks (Redis reachable? migrations applied?) and
  returns 503 with per-check detail until all pass. Kubernetes-native.
- **Auth is helpers, not takeover**: ProdKit never globally intercepts auth;
  it provides ready-made `Depends()` objects. Route protection stays visible
  in the user's code.
- **Rate limiting default backend** is in-memory (single-process only) with a
  loud startup warning if `workers > 1` is detected; Redis backend for real
  deployments.

---

## CLI

```
prodkit init        # scaffold prodkit.toml + optional example app
prodkit doctor      # production-readiness audit with score
prodkit inspect     # show resolved config, active plugins, middleware order
prodkit generate    # deployment file generators (subcommands below)
  ├─ docker         # Dockerfile (multi-stage, non-root, healthcheck)
  ├─ compose        # docker-compose.yml
  ├─ nginx          # reverse-proxy config (TLS, gzip, proxy headers)
  ├─ github         # GitHub Actions CI workflow
  └─ env            # .env.example from resolved config schema
prodkit plugins     # list discovered/active plugins with versions
```

### `prodkit doctor`

Static + runtime audit. Each plugin contributes checks via its `doctor()` hook:

```
$ prodkit doctor

  Security headers        ✔
  HTTPS redirect          ✔  (production profile)
  Trusted hosts           ✔
  Structured logging      ✔  (json)
  Request IDs             ✔
  Health endpoints        ✔  /health /ready
  Error normalization     ✔
  Compression             ✔  gzip+brotli
  Metrics                 ✔  /metrics
  Rate limiting           ✖  disabled — recommended for public APIs
  Redis                   ✖  configured but unreachable (localhost:6379)
  Secrets in env          ⚠  JWT_SECRET appears low-entropy

  Production score: 84/100
  Run with --strict to exit non-zero below 90 (CI gate).
```

`--strict` makes doctor a CI quality gate — this is the killer feature for
team adoption.

---

## Project Layout

```
prodkit/
├── .github/
│   └── workflows/            # ci.yml, release.yml
├── docs/                      # mkdocs-material
│   ├── index.md
│   ├── quickstart.md
│   ├── configuration.md
│   ├── plugins/               # one page per built-in + authoring guide
│   ├── cli.md
│   ├── deployment.md
│   ├── security.md
│   └── api/                   # mkdocstrings API reference
├── examples/
│   ├── minimal/               # the one-liner
│   ├── configured/            # toml + env config
│   └── custom-plugin/         # plugin authoring example
├── src/
│   └── prodkit/
│       ├── __init__.py        # exports: Production, Plugin, configs
│       ├── py.typed
│       ├── core/
│       │   ├── production.py
│       │   ├── config.py
│       │   ├── context.py
│       │   ├── lifecycle.py
│       │   ├── registry.py
│       │   ├── event_bus.py
│       │   ├── plugin_manager.py
│       │   └── exceptions.py
│       ├── contracts/
│       │   └── plugin.py      # Plugin base, Check, middleware spec
│       ├── plugins/
│       │   ├── request_id/
│       │   ├── logging/
│       │   ├── errors/
│       │   ├── health/
│       │   ├── security/
│       │   ├── cors/
│       │   ├── compression/
│       │   ├── metrics/
│       │   ├── rate_limit/
│       │   ├── cache/
│       │   └── auth/
│       ├── cli/               # typer app: init, doctor, inspect, generate
│       ├── generators/        # docker, compose, nginx, github, env
│       └── utils/
├── tests/
│   ├── unit/
│   ├── integration/           # real ASGI TestClient flows
│   ├── plugins/               # per-plugin suites
│   └── examples/              # example apps boot & respond
├── pyproject.toml
├── README.md
├── LICENSE                    # MIT
├── CONTRIBUTING.md
├── SECURITY.md
├── CODE_OF_CONDUCT.md
└── CHANGELOG.md
```

Notes vs. a flat layout:

- **`src/` layout** — prevents accidentally importing the repo checkout
  instead of the installed package in tests; standard for modern libraries.
- **Dropped for v0.x:** standalone `middleware/`, `routing/`, `services/`,
  `integrations/`, `templates/` top-level packages. Middleware lives inside
  the plugin that owns it; a standalone `middleware/` package invites
  kernel↔plugin coupling. Add top-level packages only when two plugins
  genuinely share code.
- **`generators/`** holds Jinja2 templates next to their generator code.

### Packaging (`pyproject.toml` essentials)

```toml
[project]
name = "prodkit"
requires-python = ">=3.10"
dependencies = ["fastapi>=0.110", "pydantic>=2.5", "pydantic-settings>=2.1"]

[project.optional-dependencies]
metrics = ["prometheus-client"]
redis   = ["redis>=5"]
auth    = ["pyjwt[crypto]"]
brotli  = ["brotli"]
cli     = ["typer", "rich", "jinja2"]
all     = ["prodkit[metrics,redis,auth,brotli,cli]"]

[project.entry-points."prodkit.plugins"]
# third-party packages register their plugins here
```

---

## Testing Strategy

| Layer             | Tooling                                | What it proves                                  |
|-------------------|----------------------------------------|--------------------------------------------------|
| Unit              | pytest                                 | Kernel logic: config precedence, topo-sort, priority ordering, registry |
| Contract          | shared pytest fixtures                 | Every plugin honors the Plugin contract (hooks callable, idempotent configure, clean shutdown) |
| Integration       | `TestClient` / httpx ASGI              | Real request flows: request-ID propagation into logs, 503 from `/ready` when a check fails, rate-limit 429s |
| Compatibility     | tox/nox matrix                         | Python 3.10–3.13 × FastAPI min-pinned and latest — critical, FastAPI moves fast |
| Property          | hypothesis (targeted)                  | Config parsing, header merging                   |
| Examples          | pytest booting each `examples/` app    | Docs never lie                                   |
| CLI               | typer's CliRunner                      | Generators produce valid output (lint generated Dockerfile/nginx conf) |

Target: **90%+ coverage**, enforced in CI. Plus the import-linter contract:
`prodkit.core` may not import `prodkit.plugins`.

---

## CI/CD

**Every PR:** ruff (lint+format) → mypy --strict → pytest with coverage gate →
compatibility matrix → `python -m build` → import-linter.

**On release tag:** build → publish to PyPI via **Trusted Publishing** (OIDC,
no long-lived tokens) → GitHub Release with auto-changelog → deploy docs.

Conventional Commits drive automated changelog and version bumping
(release-please or python-semantic-release).

---

## Roadmap

Ordered so that each release is independently valuable and the plugin SDK is
proven *by* the built-ins before it's made public.

### v0.1.0 — Core (the credible one-liner)
- Kernel: config, context, registry, plugin manager (topo-sort), lifecycle (lifespan wrapping), event bus
- Plugin contract (async hooks, priorities) — internal, may still change
- Plugins: request-id, logging, errors, health, security, cors, compression
- Environment profiles (dev/staging/prod)
- Docs: quickstart, configuration, per-plugin pages
- 90% coverage, CI matrix, PyPI publish

### v0.2.0 — Doctor + CLI foundation  *(doctor early: it's the adoption hook)* — ✅ shipped
- `prodkit doctor` (+ `--strict` CI gate), `inspect`, `init`, `plugins`
- Rate limiting (in-memory backend)
- Response/error standardization hardening (`instance` member, shared builder)

### v0.3.0 — Observability & backends
- Prometheus metrics plugin
- Redis backend (cache service + rate-limit backend)
- OpenTelemetry tracing (extra)

### v0.4.0 — Generators
- `prodkit generate docker|compose|nginx|github|env`
- Generated files linted in CI (hadolint, nginx -t in container)

### v0.5.0 — Plugin SDK & ecosystem
- Public, documented, stability-marked plugin API
- Entry-point discovery finalized
- Plugin authoring guide + cookiecutter template
- First companion packages: `prodkit-sentry`, `prodkit-opentelemetry`

### v0.6.0 — Auth helpers
- JWT validation, API-key dependencies, OAuth2 helpers
- *(deliberately late: auth is where security bugs live; ship it after the
  contract is stable and review bandwidth exists — a CVE in an early release
  kills the project's "production-ready" credibility)*

### v1.0.0 — Stable
- Frozen public API (kernel + plugin contract), deprecation policy
- LTS commitment, upgrade guide, production case studies

---

## Coding Standards

- Python **3.10+**, full type hints, `py.typed`
- **ruff** (lint + format), **mypy --strict**, **pytest**
- Docstrings on all public APIs (Google style, rendered by mkdocstrings)
- **SemVer** + **Conventional Commits** (`feat:` `fix:` `docs:` `refactor:`
  `perf:` `test:` `build:` `ci:` `chore:`)
- Public API = what's exported from `prodkit/__init__.py` and documented;
  everything else is private regardless of underscore

### Branching — trunk-based

```
main          # always releasable; releases are tags on main
feature/*     # short-lived PR branches
hotfix/*      # only if a release needs patching from a tag
```

A `develop` branch adds ceremony without value for a library published from
tags; CI on `main` is the integration gate.

---

## Success Metrics

Vanity milestones (stars/downloads) are lagging indicators. Leading indicators
to actually steer by:

| Metric                                    | Target        |
|-------------------------------------------|---------------|
| Time from `pip install` to production-scored app | < 5 minutes |
| `prodkit doctor` adopted as a CI gate     | in the wild by v0.3 |
| Third-party plugins published             | 3+ by v0.6    |
| Issues answered within                    | 48h           |
| Then: 1k stars → 10k stars → 1M downloads → 100+ contributors |

---

## FAQ / Design Decisions

**Why not just copy a FastAPI production template?**
Templates rot in every repo that copies them. A library ships fixes and new
best practices to everyone via `pip install -U`.

**Does `Production(app)` replace my app?**
No. It mutates/wraps the same FastAPI instance. All your routes, dependencies,
and existing middleware keep working; ProdKit's middleware is ordered around
them deterministically.

**What if I already have a lifespan / logging / CORS setup?**
Each plugin can be disabled (`Production(app, cors=False)`), and existing
lifespans are composed, not replaced. ProdKit detects duplicate middleware
(e.g. a user-added CORSMiddleware) and warns via `doctor`.

**Multi-worker awareness?**
In-memory backends (rate limit, cache) warn loudly under multiple workers and
document the Redis path. No silent per-worker inconsistency.

**Why is auth so late in the roadmap?**
Because "production framework ships auth bug" is an extinction-level headline
for this project. Everything before it builds the test/review infrastructure
that auth requires.

---

## License

MIT

---

*ProdKit — because `Production(app)` should be the second line of every
FastAPI service.*
