# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-07-23

### Changed
- README polish: PyPI/Python badges, table of contents, `prodkit[cli]` install
  note, rate-limiting shown in the config examples, and a `doctor()` hook in the
  plugin-authoring example. Docs-only release (no code changes).

## [0.2.0] - 2026-07-22

### Added
- **`prodkit` CLI** (install with `pip install prodkit[cli]`):
  - `prodkit doctor` — production-readiness audit with a weighted 0–100 score;
    `--strict --min-score N` turns it into a CI gate (non-zero exit below the
    threshold).
  - `prodkit inspect` — resolved config, active plugins, and middleware order.
  - `prodkit plugins` — active plugins and the hooks each implements.
  - `prodkit init [--example]` — scaffold a `prodkit.toml` (and starter app).
- **`Plugin.doctor(ctx)` hook** returning `Audit` findings; implemented by every
  built-in plugin. `Audit` (name, status `ok`/`warn`/`fail`, detail,
  recommendation, weight) is exported from the top-level package.
- Kernel doctor engine (`prodkit.core.doctor`) aggregating plugin audits with
  config-level checks (environment, debug, disabled rate-limiting, low-entropy
  secrets in the environment) into a score.
- **Rate-limiting plugin** (`rate-limit`, off by default): in-memory
  fixed-window per-IP limiting (`rate_limit={"default": "100/minute"}`),
  returning `429 application/problem+json` with a `Retry-After` header. Logs a
  per-process-backend warning (shared Redis backend arrives in v0.3).

### Changed
- Error responses now include an `instance` member (the request path). All
  framework errors — including the rate limiter's 429 — share one
  `problem_response` builder for a consistent RFC 9457 shape.

## [0.1.3] - 2026-07-20

### Changed
- README updated (badge cleanup); republished so the PyPI project page shows
  the current README.

## [0.1.1] - 2026-07-20

### Fixed
- README links that were relative (LICENSE, docs/ARCHITECTURE.md,
  CONTRIBUTING.md, SECURITY.md) now use absolute GitHub URLs so they work on
  the PyPI project page.

### Changed
- Package author set to Pushkar Pant with contact email; author section added
  to the README.

## [0.1.0] - 2026-07-16

### Added
- Kernel: layered configuration (args > env > `prodkit.toml` > profile > defaults),
  plugin manager with dependency topological sort, service registry, event bus,
  lifespan composition, fail-fast config validation.
- Plugin contract with async startup/shutdown hooks and prioritized middleware
  registration.
- Environment profiles: `development`, `staging`, `production`.
- Built-in plugins: `request-id`, `logging` (structured JSON/console), `errors`
  (RFC 9457 problem+json), `health` (`/health`, `/ready`, `/live`), `security`
  (security headers, trusted hosts, HTTPS redirect), `cors`, `compression` (gzip).
- `Production(app)` one-line entrypoint.
