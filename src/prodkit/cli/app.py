"""The typer + rich CLI application: doctor, inspect, plugins, init."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from prodkit import __version__
from prodkit.cli.loader import AppLoadError, load_production
from prodkit.contracts.plugin import Plugin
from prodkit.core.doctor import DoctorReport, run_doctor

app = typer.Typer(
    name="prodkit",
    help="Audit and inspect the production-readiness of a FastAPI app.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

_APP_OPTION = typer.Option(
    None,
    "--app",
    "-a",
    metavar="MODULE:ATTR",
    help="Import path to your FastAPI app (default: autodetect main:app, app:app, ...).",
)


def _supports_unicode() -> bool:
    """Whether the output stream can encode the status glyphs.

    Windows terminals often default to cp1252, which can't encode ✔/⚠/✖; fall
    back to ASCII markers there instead of crashing on a UnicodeEncodeError.
    """
    encoding = console.encoding or "utf-8"
    try:
        "✔⚠✖".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


_STATUS_ICON = (
    {"ok": "[green]✔[/]", "warn": "[yellow]⚠[/]", "fail": "[red]✖[/]"}
    if _supports_unicode()
    else {"ok": "[green]OK[/]", "warn": "[yellow]![/]", "fail": "[red]X[/]"}
)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"prodkit {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    _version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """ProdKit CLI."""


def _load(app_spec: str | None):  # type: ignore[no-untyped-def]
    try:
        return load_production(app_spec)
    except AppLoadError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(2) from None


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------
def _render_doctor(report: DoctorReport) -> None:
    table = Table(title="Production readiness", show_lines=False, expand=False)
    table.add_column("", justify="center", no_wrap=True)
    table.add_column("Check", style="bold")
    table.add_column("Detail")
    table.add_column("Recommendation", style="dim")
    for audit in report.audits:
        table.add_row(
            _STATUS_ICON[audit.status], audit.name, audit.detail, audit.recommendation or ""
        )
    console.print(table)

    score = report.score
    color = "green" if score >= 90 else "yellow" if score >= 70 else "red"
    summary = f"[{color}]Production score: {score}/100[/]"
    if report.failures:
        summary += f"   [red]{len(report.failures)} failing[/]"
    if report.warnings:
        summary += f"   [yellow]{len(report.warnings)} warning(s)[/]"
    console.print(Panel(summary, expand=False))


@app.command()
def doctor(
    app_spec: str | None = _APP_OPTION,
    strict: bool = typer.Option(
        False, "--strict", help="Exit non-zero when the score is below --min-score (CI gate)."
    ),
    min_score: int = typer.Option(90, "--min-score", help="Passing threshold for --strict."),
) -> None:
    """Audit a FastAPI app and print a production-readiness score."""
    report = run_doctor(_load(app_spec))
    _render_doctor(report)
    if strict and report.score < min_score:
        err_console.print(
            f"[red]doctor: score {report.score} is below the required {min_score}[/]"
        )
        raise typer.Exit(1)


# --------------------------------------------------------------------------
# inspect
# --------------------------------------------------------------------------
def _overridden_hooks(plugin: Plugin) -> list[str]:
    hooks = (
        "configure",
        "register_middleware",
        "register_routes",
        "startup",
        "shutdown",
        "checks",
        "doctor",
    )
    return [h for h in hooks if getattr(type(plugin), h) is not getattr(Plugin, h)]


@app.command()
def inspect(app_spec: str | None = _APP_OPTION) -> None:
    """Show the resolved config, active plugins, and middleware order."""
    prod = _load(app_spec)

    console.print(Panel(f"[bold]environment:[/] {prod.config.environment}", expand=False))

    console.print("[bold]Resolved configuration[/]")
    console.print_json(json.dumps(prod.config.model_dump(mode="json")))

    plugins_table = Table(title="Active plugins", expand=False)
    plugins_table.add_column("Plugin", style="bold")
    plugins_table.add_column("Requires")
    plugins_table.add_column("Hooks", style="dim")
    for plugin in prod.plugins:
        plugins_table.add_row(
            plugin.name,
            ", ".join(plugin.requires) or "-",
            ", ".join(_overridden_hooks(plugin)) or "-",
        )
    console.print(plugins_table)

    mw_table = Table(title="Middleware order (outermost first)", expand=False)
    mw_table.add_column("Priority", justify="right")
    mw_table.add_column("Middleware", style="bold")
    mw_table.add_column("From plugin", style="dim")
    for spec in sorted(prod.context.middleware_specs(), key=lambda s: s.priority):
        mw_table.add_row(str(spec.priority), spec.cls.__name__, spec.plugin or "-")
    console.print(mw_table)


# --------------------------------------------------------------------------
# plugins
# --------------------------------------------------------------------------
@app.command()
def plugins(app_spec: str | None = _APP_OPTION) -> None:
    """List the active plugins and the hooks each one implements."""
    prod = _load(app_spec)
    table = Table(title="Active plugins", expand=False)
    table.add_column("Plugin", style="bold")
    table.add_column("Requires")
    table.add_column("Hooks", style="dim")
    for plugin in prod.plugins:
        table.add_row(
            plugin.name,
            ", ".join(plugin.requires) or "-",
            ", ".join(_overridden_hooks(plugin)) or "-",
        )
    console.print(table)
    console.print(f"[green]{len(prod.plugins)}[/] plugin(s) active.")


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------
_TOML_TEMPLATE = """\
# prodkit.toml — ProdKit configuration
# Resolution order (highest wins): Python args > env vars > this file > profile defaults
[prodkit]
environment = "production"

[logging]
level = "INFO"
format = "json"

[security]
hsts = true
# trusted_hosts = ["api.example.com"]

[cors]
enabled = false
# origins = ["https://app.example.com"]

[rate_limit]
enabled = false
default = "100/minute"

[compression]
minimum_size = 500
"""

_EXAMPLE_TEMPLATE = """\
from fastapi import FastAPI

from prodkit import Production

app = FastAPI()
Production(app)


@app.get("/")
def root():
    return {"message": "production ready"}
"""


@app.command()
def init(
    path: Path = typer.Option(Path("."), "--path", help="Directory to write files into."),
    example: bool = typer.Option(False, "--example", help="Also scaffold a minimal main.py."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
) -> None:
    """Scaffold a prodkit.toml (and optionally a starter app)."""
    path.mkdir(parents=True, exist_ok=True)
    toml_path = path / "prodkit.toml"
    if toml_path.exists() and not force:
        err_console.print(f"[red]error:[/] {toml_path} already exists (use --force to overwrite)")
        raise typer.Exit(2)
    toml_path.write_text(_TOML_TEMPLATE, encoding="utf-8")
    console.print(f"[green]created[/] {toml_path}")

    if example:
        main_path = path / "main.py"
        if main_path.exists() and not force:
            err_console.print(f"[yellow]skipped[/] {main_path} already exists")
        else:
            main_path.write_text(_EXAMPLE_TEMPLATE, encoding="utf-8")
            console.print(f"[green]created[/] {main_path}")
