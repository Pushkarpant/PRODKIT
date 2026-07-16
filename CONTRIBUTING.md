# Contributing to ProdKit

Thanks for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/prodkit/prodkit
cd prodkit
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Quality Gates (run before pushing)

```bash
ruff check src tests
ruff format --check src tests
mypy
pytest
lint-imports
```

All of these run in CI on every pull request and must pass.

## Rules

- **Python 3.10+**, full type hints, docstrings on public APIs.
- **The kernel (`prodkit.core`, `prodkit.contracts`) must never import from
  `prodkit.plugins`** — enforced by import-linter.
- Every plugin needs unit tests and at least one integration test exercising a
  real request through `TestClient`.
- Coverage must stay at or above 90%.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org):
  `feat:`, `fix:`, `docs:`, `refactor:`, `perf:`, `test:`, `build:`, `ci:`, `chore:`.
- Security-sensitive changes (headers, error handling, anything in the
  `security` plugin) require extra review — mention it in the PR description.

## Branching

- `main` is always releasable; releases are tags on `main`.
- Work on short-lived `feature/*` branches and open a PR.

## Reporting Security Issues

See [SECURITY.md](SECURITY.md) — never open public issues for vulnerabilities.
