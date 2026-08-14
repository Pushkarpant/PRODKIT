"""Unit tests for prodkit deployment generators."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from prodkit import (
    CacheConfig,
    MetricsConfig,
    Production,
    RateLimitConfig,
)
from prodkit.generators import (
    ALL_GENERATORS,
    ComposeGenerator,
    DockerGenerator,
    EnvGenerator,
    GeneratorContext,
    GitHubGenerator,
    NginxGenerator,
)


class TestDockerGenerator:
    def test_default_generation(self) -> None:
        gen = DockerGenerator()
        ctx = GeneratorContext()
        files = gen.generate(ctx)

        assert len(files) == 2
        paths = [f.path for f in files]
        assert Path("Dockerfile") in paths
        assert Path(".dockerignore") in paths

        dockerfile = next(f for f in files if f.path == Path("Dockerfile"))
        assert "FROM python:3.12-slim AS builder" in dockerfile.content
        assert "USER appuser" in dockerfile.content
        assert "EXPOSE 8000" in dockerfile.content
        assert "http://localhost:8000/health" in dockerfile.content
        assert 'CMD ["uvicorn", "main:app"' in dockerfile.content

        dockerignore = next(f for f in files if f.path == Path(".dockerignore"))
        assert ".git" in dockerignore.content
        assert ".venv/" in dockerignore.content
        assert "__pycache__/" in dockerignore.content

    def test_custom_port_and_health(self) -> None:
        app = FastAPI()
        prod = Production(app, health={"health_path": "/api/v1/ping"})
        ctx = GeneratorContext(
            production=prod,
            port=9000,
            app_spec="src.app:api",
        )
        files = DockerGenerator().generate(ctx)
        dockerfile = next(f for f in files if f.path == Path("Dockerfile"))

        assert "EXPOSE 9000" in dockerfile.content
        expected_cmd = 'CMD ["uvicorn", "src.app:api", "--host", "0.0.0.0", "--port", "9000"'
        assert expected_cmd in dockerfile.content


class TestComposeGenerator:
    def test_default_without_redis(self) -> None:
        gen = ComposeGenerator()
        ctx = GeneratorContext(port=8080)
        files = gen.generate(ctx)

        assert len(files) == 1
        compose = files[0]
        assert compose.path == Path("docker-compose.yml")
        assert "services:" in compose.content
        assert "app:" in compose.content
        assert "PORT=8080" in compose.content
        assert "redis:" not in compose.content
        assert "redis_data:" not in compose.content

    def test_with_redis_rate_limit(self) -> None:
        app = FastAPI()
        prod = Production(
            app,
            rate_limit=RateLimitConfig(enabled=True, backend="redis"),
        )
        ctx = GeneratorContext(production=prod)
        files = ComposeGenerator().generate(ctx)
        compose = files[0]

        assert "redis:" in compose.content
        assert "image: redis:7-alpine" in compose.content
        assert "redis_data:" in compose.content
        assert "depends_on:" in compose.content
        assert "PRODKIT_RATE_LIMIT__REDIS_URL" in compose.content

    def test_with_redis_cache(self) -> None:
        app = FastAPI()
        prod = Production(
            app,
            cache=CacheConfig(enabled=True, backend="redis"),
        )
        ctx = GeneratorContext(production=prod)
        files = ComposeGenerator().generate(ctx)
        compose = files[0]

        assert "redis:" in compose.content
        assert "PRODKIT_CACHE__REDIS_URL" in compose.content


class TestNginxGenerator:
    def test_default_generation(self) -> None:
        gen = NginxGenerator()
        ctx = GeneratorContext(port=8000)
        files = gen.generate(ctx)

        assert len(files) == 1
        nginx = files[0]
        assert nginx.path == Path("nginx.conf")
        assert "server 127.0.0.1:8000;" in nginx.content
        assert "proxy_set_header X-Request-ID $request_id;" in nginx.content
        assert "proxy_set_header traceparent $http_traceparent;" in nginx.content
        assert "location /health" in nginx.content
        assert "location /metrics" not in nginx.content

    def test_with_metrics_enabled(self) -> None:
        app = FastAPI()
        prod = Production(
            app,
            metrics=MetricsConfig(enabled=True, path="/custom-metrics"),
        )
        ctx = GeneratorContext(production=prod)
        files = NginxGenerator().generate(ctx)
        nginx = files[0]

        assert "location /custom-metrics" in nginx.content


class TestGitHubGenerator:
    def test_workflow_generation(self) -> None:
        gen = GitHubGenerator()
        ctx = GeneratorContext()
        files = gen.generate(ctx)

        assert len(files) == 1
        ci = files[0]
        assert ci.path == Path(".github/workflows/ci.yml")
        assert "matrix:" in ci.content
        assert "python-version:" in ci.content
        assert "ruff check ." in ci.content
        assert "mypy --strict" in ci.content
        assert "pytest --cov" in ci.content
        assert "prodkit.cli doctor --strict" in ci.content


class TestEnvGenerator:
    def test_env_example_generation(self) -> None:
        gen = EnvGenerator()
        ctx = GeneratorContext()
        files = gen.generate(ctx)

        assert len(files) == 1
        env = files[0]
        assert env.path == Path(".env.example")
        assert "PRODKIT_ENVIRONMENT=production" in env.content
        assert "PRODKIT_LOGGING__LEVEL=INFO" in env.content
        assert "PRODKIT_SECURITY__HSTS=true" in env.content
        assert "PRODKIT_RATE_LIMIT__BACKEND=memory" in env.content


class TestGeneratorWritingLifecycle:
    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        gen = DockerGenerator()
        ctx = GeneratorContext(root_dir=tmp_path, dry_run=True)
        results = gen.write(ctx)

        for _, status in results:
            assert status == "dry-run"

        assert not (tmp_path / "Dockerfile").exists()
        assert not (tmp_path / ".dockerignore").exists()

    def test_write_and_overwrite_and_skip(self, tmp_path: Path) -> None:
        gen = DockerGenerator()
        ctx = GeneratorContext(root_dir=tmp_path, force=False)
        results = gen.write(ctx)

        for _, status in results:
            assert status == "created"

        dockerfile = tmp_path / "Dockerfile"
        assert dockerfile.exists()
        original_content = dockerfile.read_text(encoding="utf-8")

        # Modifying the file manually to test skip
        dockerfile.write_text("custom user content", encoding="utf-8")

        # Running again without force -> should be skipped
        results_skip = gen.write(ctx)
        status_dict = {f.path: s for f, s in results_skip}
        assert status_dict[Path("Dockerfile")] == "skipped"
        assert dockerfile.read_text(encoding="utf-8") == "custom user content"

        # Running with force -> should be overwritten
        ctx_force = GeneratorContext(root_dir=tmp_path, force=True)
        results_overwrite = gen.write(ctx_force)
        status_dict_overwrite = {f.path: s for f, s in results_overwrite}
        assert status_dict_overwrite[Path("Dockerfile")] == "overwritten"
        assert dockerfile.read_text(encoding="utf-8") == original_content

    def test_all_generators_tuple(self) -> None:
        assert len(ALL_GENERATORS) == 5
