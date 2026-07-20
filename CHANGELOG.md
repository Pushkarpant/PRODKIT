# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
