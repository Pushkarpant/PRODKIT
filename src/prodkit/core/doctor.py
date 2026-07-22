"""Production-readiness audit engine behind ``prodkit doctor``.

Aggregates :class:`~prodkit.contracts.plugin.Audit` findings from every active
plugin's :meth:`~prodkit.contracts.plugin.Plugin.doctor` hook, adds a handful of
kernel-level audits derived purely from the resolved config, and rolls the lot
into a weighted 0-100 production score.

This module lives in the kernel and imports **no plugin** (only the ``Audit``
contract and config types), preserving the import-linter ``core ⇏ plugins``
contract. It reasons about plugins polymorphically via the ``Plugin`` base type.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from prodkit.contracts.plugin import Audit

if TYPE_CHECKING:
    from prodkit.core.config import ProdKitConfig
    from prodkit.core.production import Production

# Env var names that look like they hold secrets; their *values* are never
# printed — only the key name is surfaced if the value looks weak.
_SECRET_KEY_RE = re.compile(r"(SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE_KEY|API_KEY)", re.IGNORECASE)
_MIN_SECRET_LEN = 16
_MIN_SECRET_ENTROPY = 3.0  # bits per character; < this reads as low-entropy


@dataclass
class DoctorReport:
    """The result of a doctor run: individual findings plus the rolled-up score."""

    audits: list[Audit]
    score: int

    @property
    def failures(self) -> list[Audit]:
        return [a for a in self.audits if a.status == "fail"]

    @property
    def warnings(self) -> list[Audit]:
        return [a for a in self.audits if a.status == "warn"]


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(value)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _core_audits(config: ProdKitConfig, environ: dict[str, str]) -> list[Audit]:
    """Kernel-level audits computed from config + environment (no plugins)."""
    audits: list[Audit] = []
    is_prod = config.environment == "production"

    audits.append(
        Audit(
            name="Environment profile",
            status="ok" if is_prod else "warn",
            detail=config.environment,
            recommendation=("" if is_prod else "run the production profile before shipping"),
            weight=12,
        )
    )
    audits.append(
        Audit(
            name="Debug mode",
            status="fail" if config.debug else "ok",
            detail="on" if config.debug else "off",
            recommendation="turn debug off in production" if config.debug else "",
            weight=12,
        )
    )
    # Rate limiting: when the plugin is active it audits itself; surface the
    # *disabled* case here so `doctor` still recommends it (matches the docs).
    if not config.rate_limit.enabled:
        audits.append(
            Audit(
                name="Rate limiting",
                status="warn",
                detail="disabled",
                recommendation="enable for public APIs to blunt abuse and brute-force",
                weight=10,
            )
        )

    audits.append(_secrets_audit(environ))
    return audits


def _secrets_audit(environ: dict[str, str]) -> Audit:
    weak: list[str] = []
    for key, value in environ.items():
        if not _SECRET_KEY_RE.search(key):
            continue
        if len(value) < _MIN_SECRET_LEN or _shannon_entropy(value) < _MIN_SECRET_ENTROPY:
            weak.append(key)
    if weak:
        return Audit(
            name="Secrets in environment",
            status="warn",
            detail=f"low-entropy value(s): {', '.join(sorted(weak))}",
            recommendation="use long, random secrets (values are never printed)",
            weight=6,
        )
    return Audit(
        name="Secrets in environment",
        status="ok",
        detail="no obviously weak secrets detected",
        weight=6,
    )


def compute_score(audits: list[Audit]) -> int:
    """Weighted score in 0-100. ``ok`` = full weight, ``warn`` = half, ``fail`` = 0."""
    total = sum(a.weight for a in audits)
    if total == 0:
        return 100
    earned = 0.0
    for a in audits:
        if a.status == "ok":
            earned += a.weight
        elif a.status == "warn":
            earned += a.weight * 0.5
    return round(earned / total * 100)


def run_doctor(prod: Production, environ: dict[str, str] | None = None) -> DoctorReport:
    """Run every active plugin's ``doctor()`` plus kernel audits; score the result."""
    environ = dict(os.environ) if environ is None else environ
    audits = list(_core_audits(prod.config, environ))
    for plugin in prod.plugins:
        audits.extend(plugin.doctor(prod.context))
    return DoctorReport(audits=audits, score=compute_score(audits))
