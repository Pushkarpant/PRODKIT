"""Unit tests for the doctor engine: audit aggregation and scoring."""

from __future__ import annotations

from fastapi import FastAPI

from prodkit import Production
from prodkit.contracts.plugin import Audit
from prodkit.core.doctor import compute_score, run_doctor
from tests.conftest import NO_TOML


def build(**overrides) -> Production:
    overrides.setdefault("config_file", NO_TOML)
    return Production(FastAPI(), **overrides)


class TestComputeScore:
    def test_all_ok_is_100(self):
        audits = [Audit("a", "ok", weight=10), Audit("b", "ok", weight=5)]
        assert compute_score(audits) == 100

    def test_warn_is_half_credit(self):
        assert compute_score([Audit("a", "warn", weight=10)]) == 50

    def test_fail_is_no_credit(self):
        audits = [Audit("a", "ok", weight=10), Audit("b", "fail", weight=10)]
        assert compute_score(audits) == 50

    def test_empty_is_100(self):
        assert compute_score([]) == 100

    def test_weighting(self):
        # 30/40 -> 75
        audits = [Audit("a", "ok", weight=30), Audit("b", "fail", weight=10)]
        assert compute_score(audits) == 75


class TestRunDoctor:
    def test_production_app_scores_high(self):
        prod = build(environment="production", cors={"origins": ["https://a.example.com"]})
        report = run_doctor(prod, environ={})
        names = {a.name for a in report.audits}
        assert "Security headers" in names
        assert "Structured logging" in names
        assert "Error normalization" in names
        assert report.score >= 70

    def test_disabled_rate_limit_warns(self):
        prod = build(environment="production")
        report = run_doctor(prod, environ={})
        rl = [a for a in report.audits if a.name == "Rate limiting"]
        assert rl and rl[0].status == "warn"

    def test_enabled_rate_limit_is_ok(self):
        prod = build(environment="production", rate_limit={"default": "50/minute"})
        report = run_doctor(prod, environ={})
        rl = [a for a in report.audits if a.name == "Rate limiting"]
        assert rl and rl[0].status == "ok"

    def test_development_profile_warns_on_environment(self):
        prod = build(environment="development")
        report = run_doctor(prod, environ={})
        env = [a for a in report.audits if a.name == "Environment profile"]
        assert env and env[0].status == "warn"

    def test_weak_secret_in_env_warns(self):
        prod = build(environment="production")
        report = run_doctor(prod, environ={"APP_SECRET": "123"})
        sec = [a for a in report.audits if a.name == "Secrets in environment"]
        assert sec and sec[0].status == "warn"
        # the value itself is never printed
        assert "123" not in sec[0].detail

    def test_strong_secret_in_env_is_ok(self):
        prod = build(environment="production")
        report = run_doctor(prod, environ={"APP_SECRET": "9f3a7Dx2Kq8vLm4Zr1Wn6Bt0Yc5Hu"})
        sec = [a for a in report.audits if a.name == "Secrets in environment"]
        assert sec and sec[0].status == "ok"

    def test_missing_csp_warns(self):
        prod = build(environment="production")
        report = run_doctor(prod, environ={})
        csp = [a for a in report.audits if a.name == "Content-Security-Policy"]
        assert csp and csp[0].status == "warn"

    def test_report_failures_and_warnings_helpers(self):
        prod = build(environment="development")  # debug -> fail, env -> warn
        report = run_doctor(prod, environ={})
        assert any(a.name == "Debug mode" for a in report.failures)
        assert all(a.status == "warn" for a in report.warnings)
