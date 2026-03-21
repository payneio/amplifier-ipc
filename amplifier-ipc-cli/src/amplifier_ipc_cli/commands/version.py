"""Version command — displays CLI and host package versions."""

from __future__ import annotations

import importlib.metadata

import click

from amplifier_ipc_cli import __version__
from amplifier_ipc_cli.console import console


def _get_host_version() -> str:
    """Return the installed amplifier-ipc-host package version, or 'unknown' on failure."""
    try:
        return importlib.metadata.version("amplifier-ipc-host")
    except Exception:  # noqa: BLE001
        return "unknown"


@click.command()
def version() -> None:
    """Display the CLI and amplifier-ipc-host versions."""
    host_version = _get_host_version()
    console.print(
        f"amplifier-ipc-cli {__version__} (amplifier-ipc-host {host_version})"
    )
