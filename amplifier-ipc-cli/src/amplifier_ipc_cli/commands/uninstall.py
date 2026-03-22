"""Uninstall command — remove an environment directory without unregistering."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from amplifier_ipc_cli.registry import Registry


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
def uninstall(name: str, kind: str, home: Optional[Path]) -> None:
    """Remove the installed environment for a definition without unregistering it.

    Resolves NAME from the registry (agent first, then behavior unless --type
    is specified), then removes the environment directory if it exists.  The
    definition file and alias entries are left intact — use ``unregister`` to
    remove those as well.
    """
    registry = Registry(home=home)

    # Resolve name: honour --type if given, otherwise try agent → behavior.
    def_path = None
    if kind == "behavior":
        try:
            def_path = registry.resolve_behavior(name)
        except FileNotFoundError:
            pass
    else:
        # Default: try agent first, then behavior as fallback.
        try:
            def_path = registry.resolve_agent(name)
        except FileNotFoundError:
            try:
                def_path = registry.resolve_behavior(name)
            except FileNotFoundError:
                pass

    if def_path is None:
        raise click.ClickException(
            f"'{name}' not found in registry as an agent or behavior. "
            "Run amplifier-ipc register to add it first."
        )

    definition_id = def_path.stem
    removed = registry.uninstall_environment(definition_id)

    if removed:
        click.echo(f"Environment removed: {definition_id}")
    else:
        click.echo(f"Not installed (skipped): {definition_id}")
