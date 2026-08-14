"""GitHub Actions workflow generator: creates .github/workflows/ci.yml."""

from __future__ import annotations

from pathlib import Path

from prodkit.generators.base import BaseGenerator, GeneratedFile, GeneratorContext

_GITHUB_CI_TEMPLATE = """\
# ==============================================================================
# GitHub Actions CI Workflow for FastAPI + ProdKit
# ==============================================================================

name: CI

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    name: Test & Audit (Python ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: "pip"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f pyproject.toml ]; then
            pip install -e ".[dev]" || pip install -e .
          elif [ -f requirements.txt ]; then
            pip install -r requirements.txt
          fi
          pip install ruff mypy pytest pytest-cov typer rich

      - name: Lint and formatting checks (ruff)
        run: |
          ruff check .
          ruff format --check .

      - name: Type checking (mypy)
        run: |
          mypy --strict .

      - name: Run test suite with coverage
        run: |
          pytest --cov --cov-report=term-missing --cov-fail-under=90

      - name: ProdKit production readiness gate
        run: |
          python -m prodkit.cli doctor --strict --min-score 90
"""


class GitHubGenerator(BaseGenerator):
    """Generates GitHub Actions CI pipeline with lint, type-check, test, and doctor audit."""

    name = "github"
    description = "Generate a GitHub Actions CI workflow (.github/workflows/ci.yml)"

    def generate(self, ctx: GeneratorContext) -> list[GeneratedFile]:
        return [
            GeneratedFile(
                path=Path(".github/workflows/ci.yml"),
                content=_GITHUB_CI_TEMPLATE,
                description="GitHub Actions CI quality and testing workflow",
            )
        ]
