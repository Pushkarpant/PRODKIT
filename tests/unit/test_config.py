"""Unit tests for layered config resolution and production safety checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from prodkit.core.config import resolve_config
from prodkit.core.exceptions import ProdKitConfigError

NO_TOML = Path("nonexistent-prodkit.toml")


def resolve(overrides=None, environ=None, toml_path=NO_TOML):
    return resolve_config(overrides, toml_path=toml_path, environ=environ or {})


class TestDefaults:
    def test_default_environment_is_production(self):
        config = resolve()
        assert config.environment == "production"
        assert config.debug is False
        assert config.logging.format == "json"
        assert config.security.hsts is True

    def test_development_profile_flips_defaults(self):
        config = resolve({"environment": "development"})
        assert config.debug is True
        assert config.logging.format == "console"
        assert config.security.hsts is False
        assert config.errors.include_debug_details is True


class TestPrecedence:
    def test_env_var_overrides_profile_default(self):
        config = resolve(environ={"PRODKIT_LOGGING__LEVEL": "WARNING"})
        assert config.logging.level == "WARNING"

    def test_python_args_override_env_vars(self):
        config = resolve(
            {"logging": {"level": "ERROR"}},
            environ={"PRODKIT_LOGGING__LEVEL": "WARNING"},
        )
        assert config.logging.level == "ERROR"

    def test_toml_overridden_by_env(self, tmp_path):
        toml = tmp_path / "prodkit.toml"
        toml.write_text('[logging]\nlevel = "DEBUG"\nformat = "json"\n')
        config = resolve(
            environ={"PRODKIT_LOGGING__LEVEL": "WARNING", "PRODKIT_ENVIRONMENT": "staging"},
            toml_path=toml,
        )
        assert config.logging.level == "WARNING"  # env wins
        assert config.logging.format == "json"  # toml survives where env silent

    def test_toml_prodkit_table_sets_top_level(self, tmp_path):
        toml = tmp_path / "prodkit.toml"
        toml.write_text('[prodkit]\nenvironment = "development"\n')
        config = resolve(toml_path=toml)
        assert config.environment == "development"

    def test_none_overrides_are_ignored(self):
        config = resolve({"environment": None})
        assert config.environment == "production"


class TestEnvParsing:
    def test_bool_and_list_parsing(self):
        config = resolve(
            {"environment": "development"},
            environ={
                "PRODKIT_DEBUG": "false",
                "PRODKIT_SECURITY__TRUSTED_HOSTS": "api.example.com, admin.example.com",
            },
        )
        assert config.debug is False
        assert config.security.trusted_hosts == ["api.example.com", "admin.example.com"]

    def test_unrelated_env_vars_ignored(self):
        config = resolve(environ={"PATH": "/usr/bin", "PRODKIT_DEBUG": "0"})
        assert config.debug is False


class TestFailFast:
    def test_unknown_key_rejected(self):
        with pytest.raises(ProdKitConfigError, match=r"logging\.levle"):
            resolve({"logging": {"levle": "INFO"}})

    def test_unknown_environment_rejected(self):
        with pytest.raises(ProdKitConfigError, match="Unknown environment"):
            resolve({"environment": "prod"})

    def test_invalid_toml_rejected(self, tmp_path):
        toml = tmp_path / "prodkit.toml"
        toml.write_text("this is not toml [")
        with pytest.raises(ProdKitConfigError, match="Invalid TOML"):
            resolve(toml_path=toml)


class TestProductionSafety:
    def test_debug_true_refused_in_production(self):
        with pytest.raises(ProdKitConfigError, match="debug=True"):
            resolve({"debug": True})

    def test_debug_details_refused_in_production(self):
        with pytest.raises(ProdKitConfigError, match="leak tracebacks"):
            resolve({"errors": {"include_debug_details": True}})

    def test_wildcard_cors_with_credentials_refused_in_production(self):
        with pytest.raises(ProdKitConfigError, match="authenticated requests"):
            resolve(
                {
                    "cors": {
                        "enabled": True,
                        "origins": ["*"],
                        "allow_credentials": True,
                    }
                }
            )

    def test_same_config_allowed_in_development(self):
        config = resolve({"environment": "development", "debug": True})
        assert config.debug is True
