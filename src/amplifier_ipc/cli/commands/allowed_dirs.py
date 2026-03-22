"""Allowed write-path management commands for amplifier-ipc-cli.

Provides CLI subcommands for listing, adding, and removing allowed write
paths used by the tool-filesystem permission system.
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.table import Table

from amplifier_ipc.cli.console import console
from amplifier_ipc.cli.settings import AppSettings, get_settings

# -- Module-level helpers (patchable) -----------------------------------------


def _get_settings() -> AppSettings:
    """Return an AppSettings instance (patchable for tests)."""
    return get_settings()


# -- Allowed-dirs group -------------------------------------------------------


@click.group(name="allowed-dirs", invoke_without_command=True)
@click.pass_context
def allowed_dirs_group(ctx: click.Context) -> None:
    """Manage allowed write paths for tool-filesystem."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# -- list ---------------------------------------------------------------------


@allowed_dirs_group.command(name="list")
def list_dirs() -> None:
    """List configured allowed write paths."""
    settings = _get_settings()
    paths = settings.get_allowed_write_paths()

    if not paths:
        console.print("No allowed directories configured.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Path", style="green")
    table.add_column("Scope", style="yellow")

    for path, scope in paths:
        table.add_row(path, scope)

    console.print(table)


# -- add ----------------------------------------------------------------------


@allowed_dirs_group.command(name="add")
@click.argument("path")
@click.option("--local", "scope", flag_value="local", help="Write to local scope.")
@click.option(
    "--project", "scope", flag_value="project", help="Write to project scope."
)
@click.option(
    "--global",
    "scope",
    flag_value="global",
    default=True,
    help="Write to global scope (default).",
)
def add_dir(path: str, scope: str) -> None:
    """Add PATH to allowed write paths.

    PATH is the directory to allow. Resolved to an absolute path.
    """
    settings = _get_settings()
    resolved = Path(path).expanduser().resolve()
    settings.add_allowed_write_path(str(resolved), scope)  # type: ignore[arg-type]
    console.print(
        f"Added [green]{resolved}[/green] to allowed paths ([yellow]{scope}[/yellow])."
    )


# -- remove -------------------------------------------------------------------


@allowed_dirs_group.command(name="remove")
@click.argument("path")
@click.option("--local", "scope", flag_value="local", help="Remove from local scope.")
@click.option(
    "--project", "scope", flag_value="project", help="Remove from project scope."
)
@click.option(
    "--global",
    "scope",
    flag_value="global",
    default=True,
    help="Remove from global scope (default).",
)
def remove_dir(path: str, scope: str) -> None:
    """Remove PATH from allowed write paths.

    PATH is the directory to remove. Resolved to an absolute path.
    """
    settings = _get_settings()
    resolved = Path(path).expanduser().resolve()
    removed = settings.remove_allowed_write_path(str(resolved), scope)  # type: ignore[arg-type]
    if removed:
        console.print(f"Removed [green]{resolved}[/green] from allowed paths.")
    else:
        console.print(f"Path not found: [green]{resolved}[/green]")
