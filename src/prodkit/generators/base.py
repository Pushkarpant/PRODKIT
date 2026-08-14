"""Base classes, data models, and protocol for deployment generators."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from prodkit.core.production import Production


FileStatus = Literal["created", "skipped", "overwritten", "dry-run"]


@dataclass
class GeneratedFile:
    """A generated file artifact with a relative destination path and content."""

    path: Path
    content: str
    description: str = ""


@dataclass
class GeneratorContext:
    """Context passed to generators during template rendering and file writing."""

    production: Production | None = None
    root_dir: Path = field(default_factory=lambda: Path("."))
    force: bool = False
    dry_run: bool = False
    port: int = 8000
    app_spec: str = "main:app"

    @property
    def health_path(self) -> str:
        if self.production is not None:
            return self.production.config.health.health_path
        return "/health"

    @property
    def live_path(self) -> str:
        if self.production is not None:
            return self.production.config.health.live_path
        return "/live"

    @property
    def metrics_path(self) -> str:
        if self.production is not None:
            return self.production.config.metrics.path
        return "/metrics"

    @property
    def metrics_enabled(self) -> bool:
        if self.production is not None:
            return self.production.config.metrics.enabled
        return False

    @property
    def has_redis(self) -> bool:
        if self.production is not None:
            cfg = self.production.config
            if cfg.rate_limit.enabled and cfg.rate_limit.backend == "redis":
                return True
            if cfg.cache.enabled and cfg.cache.backend == "redis":
                return True
        return False


class BaseGenerator(ABC):
    """Abstract base class implemented by each deployment asset generator."""

    name: str = "base"
    description: str = ""

    @abstractmethod
    def generate(self, ctx: GeneratorContext) -> list[GeneratedFile]:
        """Render templates and return the list of generated files without writing."""
        raise NotImplementedError

    def write(self, ctx: GeneratorContext) -> list[tuple[GeneratedFile, FileStatus]]:
        """Render and optionally write the files to disk based on context options."""
        generated_files = self.generate(ctx)
        results: list[tuple[GeneratedFile, FileStatus]] = []

        for gen_file in generated_files:
            target_path = ctx.root_dir / gen_file.path

            if ctx.dry_run:
                results.append((gen_file, "dry-run"))
                continue

            if target_path.exists() and not ctx.force:
                results.append((gen_file, "skipped"))
                continue

            status: FileStatus = "overwritten" if target_path.exists() else "created"
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(gen_file.content, encoding="utf-8")
            results.append((gen_file, status))

        return results
