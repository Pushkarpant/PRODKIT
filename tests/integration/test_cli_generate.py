"""Integration tests for the prodkit generate CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from typer.testing import CliRunner

from prodkit import Production, RateLimitConfig
from prodkit.cli.app import app as cli_app
from prodkit.cli.loader import AppLoadError
from tests.conftest import NO_TOML

runner = CliRunner()


@pytest.fixture
def prod() -> Production:
    return Production(
        FastAPI(),
        config_file=NO_TOML,
        environment="production",
        rate_limit=RateLimitConfig(enabled=True, backend="redis"),
    )


@pytest.fixture
def patch_loader(monkeypatch: pytest.MonkeyPatch, prod: Production) -> Production:
    monkeypatch.setattr("prodkit.cli.app.load_production", lambda spec: prod)
    return prod


class TestGenerateDocker:
    def test_generate_docker(self, tmp_path: Path, patch_loader: Production) -> None:
        result = runner.invoke(cli_app, ["generate", "docker", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "Dockerfile" in result.stdout
        assert (tmp_path / "Dockerfile").exists()
        assert (tmp_path / ".dockerignore").exists()

    def test_generate_docker_dry_run(self, tmp_path: Path) -> None:
        result = runner.invoke(
            cli_app, ["generate", "docker", "--path", str(tmp_path), "--dry-run"]
        )
        assert result.exit_code == 0
        assert "dry-run" in result.stdout
        assert not (tmp_path / "Dockerfile").exists()


class TestGenerateCompose:
    def test_generate_compose_with_app(self, tmp_path: Path, patch_loader: Production) -> None:
        result = runner.invoke(cli_app, ["generate", "compose", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "docker-compose.yml" in result.stdout
        compose_file = tmp_path / "docker-compose.yml"
        assert compose_file.exists()
        assert "redis:" in compose_file.read_text(encoding="utf-8")


class TestGenerateNginx:
    def test_generate_nginx(self, tmp_path: Path, patch_loader: Production) -> None:
        result = runner.invoke(
            cli_app, ["generate", "nginx", "--path", str(tmp_path), "--port", "8080"]
        )
        assert result.exit_code == 0
        assert "nginx.conf" in result.stdout
        nginx_file = tmp_path / "nginx.conf"
        assert nginx_file.exists()
        assert "server 127.0.0.1:8080;" in nginx_file.read_text(encoding="utf-8")


class TestGenerateGitHub:
    def test_generate_github(self, tmp_path: Path) -> None:
        result = runner.invoke(cli_app, ["generate", "github", "--path", str(tmp_path)])
        assert result.exit_code == 0
        ci_file = tmp_path / ".github" / "workflows" / "ci.yml"
        assert ci_file.exists()
        assert "name: CI" in ci_file.read_text(encoding="utf-8")


class TestGenerateEnv:
    def test_generate_env(self, tmp_path: Path) -> None:
        result = runner.invoke(cli_app, ["generate", "env", "--path", str(tmp_path)])
        assert result.exit_code == 0
        env_file = tmp_path / ".env.example"
        assert env_file.exists()
        assert "PRODKIT_ENVIRONMENT=production" in env_file.read_text(encoding="utf-8")


class TestGenerateAll:
    def test_generate_all(self, tmp_path: Path, patch_loader: Production) -> None:
        result = runner.invoke(cli_app, ["generate", "all", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / "Dockerfile").exists()
        assert (tmp_path / ".dockerignore").exists()
        assert (tmp_path / "docker-compose.yml").exists()
        assert (tmp_path / "nginx.conf").exists()
        assert (tmp_path / ".github" / "workflows" / "ci.yml").exists()
        assert (tmp_path / ".env.example").exists()
        assert "Successfully generated 6 file(s)" in result.stdout

    def test_generate_all_skip_and_force(self, tmp_path: Path, patch_loader: Production) -> None:
        # First run: creates files
        runner.invoke(cli_app, ["generate", "all", "--path", str(tmp_path)])

        # Second run without force: skips existing files
        result_skip = runner.invoke(cli_app, ["generate", "all", "--path", str(tmp_path)])
        assert result_skip.exit_code == 0
        assert "skipped" in result_skip.stdout
        assert "already exist and were skipped" in result_skip.stdout

        # Third run with force: overwrites existing files
        result_force = runner.invoke(
            cli_app, ["generate", "all", "--path", str(tmp_path), "--force"]
        )
        assert result_force.exit_code == 0
        assert "overwritten" in result_force.stdout
        assert "Successfully generated 6 file(s)" in result_force.stdout


class TestGenerateErrorHandling:
    def test_explicit_app_load_error_exits_2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(spec: str | None) -> None:
            raise AppLoadError("Target application could not be imported")

        monkeypatch.setattr("prodkit.cli.app.load_production", boom)
        result = runner.invoke(cli_app, ["generate", "docker", "--app", "invalid:app"])
        assert result.exit_code == 2
        assert "Target application could not be imported" in result.stderr or result.stdout
