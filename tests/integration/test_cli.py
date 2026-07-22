"""Integration tests for the prodkit CLI (typer CliRunner)."""

from __future__ import annotations

import sys
import types

import pytest
from fastapi import FastAPI
from typer.testing import CliRunner

from prodkit import Production, __version__
from prodkit.cli.app import app as cli_app
from prodkit.cli.loader import AppLoadError, load_production
from tests.conftest import NO_TOML

runner = CliRunner()


@pytest.fixture
def prod():
    return Production(
        FastAPI(),
        config_file=NO_TOML,
        environment="production",
        cors={"origins": ["https://app.example.com"]},
    )


@pytest.fixture
def patch_loader(monkeypatch, prod):
    monkeypatch.setattr("prodkit.cli.app.load_production", lambda spec: prod)
    return prod


class TestVersion:
    def test_version_flag(self):
        result = runner.invoke(cli_app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.stdout


class TestDoctor:
    def test_doctor_prints_score(self, patch_loader):
        result = runner.invoke(cli_app, ["doctor"])
        assert result.exit_code == 0
        assert "Production score" in result.stdout

    def test_strict_below_threshold_exits_nonzero(self, patch_loader):
        result = runner.invoke(cli_app, ["doctor", "--strict", "--min-score", "100"])
        assert result.exit_code == 1

    def test_strict_met_exits_zero(self, monkeypatch, prod):
        monkeypatch.setattr("prodkit.cli.app.load_production", lambda spec: prod)
        result = runner.invoke(cli_app, ["doctor", "--strict", "--min-score", "1"])
        assert result.exit_code == 0

    def test_app_load_error_exits_2(self, monkeypatch):
        def boom(spec):
            raise AppLoadError("no app here")

        monkeypatch.setattr("prodkit.cli.app.load_production", boom)
        result = runner.invoke(cli_app, ["doctor"])
        assert result.exit_code == 2


class TestInspectAndPlugins:
    def test_inspect(self, patch_loader):
        result = runner.invoke(cli_app, ["inspect"])
        assert result.exit_code == 0
        assert "production" in result.stdout
        assert "security" in result.stdout

    def test_plugins(self, patch_loader):
        result = runner.invoke(cli_app, ["plugins"])
        assert result.exit_code == 0
        assert "security" in result.stdout
        assert "plugin(s) active" in result.stdout


class TestInit:
    def test_init_writes_toml(self, tmp_path):
        result = runner.invoke(cli_app, ["init", "--path", str(tmp_path)])
        assert result.exit_code == 0
        toml = tmp_path / "prodkit.toml"
        assert toml.exists()
        assert "[prodkit]" in toml.read_text()

    def test_init_example_writes_main(self, tmp_path):
        result = runner.invoke(cli_app, ["init", "--path", str(tmp_path), "--example"])
        assert result.exit_code == 0
        assert (tmp_path / "main.py").exists()

    def test_init_refuses_overwrite(self, tmp_path):
        (tmp_path / "prodkit.toml").write_text("existing")
        result = runner.invoke(cli_app, ["init", "--path", str(tmp_path)])
        assert result.exit_code == 2
        assert (tmp_path / "prodkit.toml").read_text() == "existing"

    def test_init_force_overwrites(self, tmp_path):
        (tmp_path / "prodkit.toml").write_text("existing")
        result = runner.invoke(cli_app, ["init", "--path", str(tmp_path), "--force"])
        assert result.exit_code == 0
        assert "[prodkit]" in (tmp_path / "prodkit.toml").read_text()


class TestLoader:
    def test_missing_module_raises(self):
        with pytest.raises(AppLoadError, match="Could not import"):
            load_production("this_module_does_not_exist_xyz:app")

    def test_app_without_production_raises(self):
        mod = types.ModuleType("fake_cli_app_mod")
        mod.app = FastAPI()  # no Production() applied
        sys.modules["fake_cli_app_mod"] = mod
        try:
            with pytest.raises(AppLoadError, match="never applied"):
                load_production("fake_cli_app_mod:app")
        finally:
            del sys.modules["fake_cli_app_mod"]

    def test_loads_production_app(self):
        mod = types.ModuleType("fake_cli_ready_mod")
        app = FastAPI()
        Production(app, config_file=NO_TOML, environment="production")
        mod.app = app
        sys.modules["fake_cli_ready_mod"] = mod
        try:
            prod = load_production("fake_cli_ready_mod:app")
            assert prod.config.environment == "production"
        finally:
            del sys.modules["fake_cli_ready_mod"]
