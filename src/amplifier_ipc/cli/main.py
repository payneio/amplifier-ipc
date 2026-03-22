"""amplifier-ipc CLI entry point and command group."""

from __future__ import annotations

import click

from amplifier_ipc.cli.commands.allowed_dirs import allowed_dirs_group
from amplifier_ipc.cli.commands.denied_dirs import denied_dirs_group
from amplifier_ipc.cli.commands.discover import discover
from amplifier_ipc.cli.commands.install import install
from amplifier_ipc.cli.commands.notify import notify_group
from amplifier_ipc.cli.commands.provider import provider_group
from amplifier_ipc.cli.commands.register import register
from amplifier_ipc.cli.commands.reset import reset_cmd
from amplifier_ipc.cli.commands.uninstall import uninstall
from amplifier_ipc.cli.commands.unregister import unregister
from amplifier_ipc.cli.commands.routing import routing_group
from amplifier_ipc.cli.commands.run import run
from amplifier_ipc.cli.commands.session import session_group
from amplifier_ipc.cli.commands.update import update
from amplifier_ipc.cli.commands.version import version


@click.group()
def cli() -> None:
    """Amplifier IPC command-line interface."""


# Core commands
cli.add_command(run)
cli.add_command(version)

# Phase 2 management commands
cli.add_command(discover)
cli.add_command(register)
cli.add_command(install)
cli.add_command(unregister)
cli.add_command(uninstall)
cli.add_command(update)
cli.add_command(session_group)

# Adapted commands
cli.add_command(provider_group)
cli.add_command(routing_group)
cli.add_command(reset_cmd)

# Wholesale from lite-cli
cli.add_command(allowed_dirs_group)
cli.add_command(denied_dirs_group)
cli.add_command(notify_group)


def main() -> None:
    """Entry point for the amplifier-ipc CLI."""
    cli()
