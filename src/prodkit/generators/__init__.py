"""Deployment and infrastructure asset generators for ProdKit."""

from __future__ import annotations

from prodkit.generators.base import (
    BaseGenerator,
    FileStatus,
    GeneratedFile,
    GeneratorContext,
)
from prodkit.generators.compose import ComposeGenerator
from prodkit.generators.docker import DockerGenerator
from prodkit.generators.env import EnvGenerator
from prodkit.generators.github import GitHubGenerator
from prodkit.generators.nginx import NginxGenerator

ALL_GENERATORS: tuple[type[BaseGenerator], ...] = (
    DockerGenerator,
    ComposeGenerator,
    NginxGenerator,
    GitHubGenerator,
    EnvGenerator,
)

__all__ = [
    "ALL_GENERATORS",
    "BaseGenerator",
    "ComposeGenerator",
    "DockerGenerator",
    "EnvGenerator",
    "FileStatus",
    "GeneratedFile",
    "GeneratorContext",
    "GitHubGenerator",
    "NginxGenerator",
]
