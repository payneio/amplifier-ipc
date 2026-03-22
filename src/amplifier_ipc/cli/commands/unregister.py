"""Unregister command — remove a definition and its environment."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from amplifier_ipc.host.definition_registry import Registry


@click.command()
@click.argument("name")
@click.option(
    "--type",
    "kind",
    type=click.Choice(["agent", "behavior"]),
    default="agent",
    show_default=True,
    help="Whether NAME is an agent or behavior definition.",
)
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Amplifier home directory (default: ~/.amplifier).",
)
def unregister(name: str, kind: str, home: Optional[Path]) -> None:
    """Remove a registered definition and its environment.

    Deletes the definition file, removes all alias entries (local_ref and
    source_url), and also removes the installed environment directory if one
    exists.  Use --type to specify whether NAME refers to an agent (default)
    or a behavior.
    """
    registry = Registry(home=home)

    try:
        definition_id = registry.unregister_definition(name, kind=kind)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Unregistered: {definition_id}")

    removed = registry.uninstall_environment(definition_id)
    if removed:
        click.echo(f"Environment removed: {definition_id}")
