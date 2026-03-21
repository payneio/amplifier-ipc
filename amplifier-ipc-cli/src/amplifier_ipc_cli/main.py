"""amplifier-ipc CLI entry point and command group."""

from __future__ import annotations

import click

from amplifier_ipc_cli.commands.allowed_dirs import allowed_dirs_group
from amplifier_ipc_cli.commands.denied_dirs import denied_dirs_group
from amplifier_ipc_cli.commands.notify import notify_group
from amplifier_ipc_cli.commands.run import run
from amplifier_ipc_cli.commands.version import version


@click.group()
def cli() -> None:
    """Amplifier IPC command-line interface."""


cli.add_command(run)
cli.add_command(version)
cli.add_command(allowed_dirs_group)
cli.add_command(denied_dirs_group)
cli.add_command(notify_group)


def main() -> None:
    """Entry point for the amplifier-ipc CLI."""
    cli()
