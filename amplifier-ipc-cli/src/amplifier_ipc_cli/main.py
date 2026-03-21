"""amplifier-ipc CLI entry point and command group."""

import click


@click.group()
def cli() -> None:
    """Amplifier IPC command-line interface."""


def main() -> None:
    """Entry point for the amplifier-ipc CLI."""
    cli()
