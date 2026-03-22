"""Routing matrix management commands for amplifier-ipc-cli."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml

from amplifier_ipc.cli.console import console
from amplifier_ipc.cli.settings import AppSettings, get_settings

# -- Module-level helpers (patchable) -----------------------------------------

_ROUTING_DIR = Path("~/.amplifier/routing")


def _get_settings() -> AppSettings:
    """Return an AppSettings instance (patchable for tests)."""
    return get_settings()


def _get_routing_dir() -> Path:
    """Return the routing directory path (patchable for tests)."""
    return _ROUTING_DIR.expanduser()


# -- Routing group ------------------------------------------------------------


@click.group(name="routing", invoke_without_command=True)
@click.pass_context
def routing_group(ctx: click.Context) -> None:
    """Manage routing matrix configuration."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# -- list ---------------------------------------------------------------------


@routing_group.command(name="list")
def list_matrices() -> None:
    """List available routing matrix YAML files in ~/.amplifier/routing/."""
    settings = _get_settings()
    routing_config = settings.get_routing_config()
    active_matrix = routing_config.get("active_matrix")

    routing_dir = _get_routing_dir()
    if not routing_dir.exists():
        console.print("No routing directory found at [dim]~/.amplifier/routing/[/dim].")
        return

    yaml_files = sorted(routing_dir.glob("*.yaml"))
    if not yaml_files:
        console.print("No routing matrix files found.")
        return

    for yaml_file in yaml_files:
        name = yaml_file.stem
        if name == active_matrix:
            console.print(f"  [green]* {name}[/green] (active)")
        else:
            console.print(f"    {name}")


# -- show ---------------------------------------------------------------------


@routing_group.command(name="show")
@click.argument("name")
def show_matrix(name: str) -> None:
    """Display roles from the routing matrix YAML file NAME."""
    routing_dir = _get_routing_dir()
    yaml_path = routing_dir / f"{name}.yaml"

    if not yaml_path.exists():
        raise click.ClickException(f"Routing matrix not found: {name}")

    try:
        raw = yaml_path.read_text(encoding="utf-8")
        data: Any = yaml.safe_load(raw)
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(f"Failed to read routing matrix: {exc}") from exc

    if not isinstance(data, dict):
        raise click.ClickException(f"Invalid routing matrix format in {name}")

    console.print(f"[bold]Routing matrix:[/bold] {name}\n")

    roles = data.get("roles", {})
    if not isinstance(roles, dict):
        console.print("[dim]No roles defined.[/dim]")
        return

    for role, config in roles.items():
        if isinstance(config, dict):
            provider = config.get("provider", "?")
            model = config.get("model", "?")
            console.print(f"  [cyan]{role}[/cyan]: {provider} / {model}")
        else:
            console.print(f"  [cyan]{role}[/cyan]: {config}")


# -- use ----------------------------------------------------------------------


@routing_group.command(name="use")
@click.argument("name")
def use_matrix(name: str) -> None:
    """Set NAME as the active routing matrix."""
    settings = _get_settings()
    settings.set_routing_matrix(name)
    console.print(f"Active routing matrix set to [green]{name}[/green].")
