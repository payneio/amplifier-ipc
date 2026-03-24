"""Agent listing and inspection commands for amplifier-ipc-cli.

Provides CLI subcommands for listing all registered agents and showing
detailed info for a specific agent from the definition registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml
from rich.panel import Panel
from rich.table import Table

from amplifier_ipc.cli.console import console
from amplifier_ipc.host.definition_registry import Registry
from amplifier_ipc.host.definitions import (
    parse_agent_definition,
    parse_behavior_definition,
)


# -- Module-level helpers (patchable) -----------------------------------------


def _get_registry() -> Registry:
    """Return a Registry instance (patchable for tests)."""
    return Registry()


# -- Internal helpers ---------------------------------------------------------


def _load_agents_alias_map(registry: Registry) -> dict[str, str]:
    """Return the raw alias → definition_id map from agents.yaml."""
    agents_yaml = registry.home / "agents.yaml"
    if not agents_yaml.exists():
        return {}
    return yaml.safe_load(agents_yaml.read_text()) or {}


def _agent_ref_names(alias_map: dict[str, str]) -> list[str]:
    """Return only ref-style aliases (no URL keys)."""
    return [k for k in alias_map if "://" not in k]


def _summarize_behaviors(agent_def: Any) -> str:
    """Return a comma-separated list of behavior aliases declared by agent_def."""
    names: list[str] = []
    for b_dict in agent_def.behaviors:
        for alias in b_dict:
            names.append(alias)
    if not names:
        return "[dim]—[/dim]"
    return ", ".join(names)


def _walk_behaviors_summary(
    registry: Registry,
    agent_def: Any,
    agent_name: str,
) -> list[dict[str, Any]]:
    """Walk the behavior tree and return a flat list of behavior info dicts.

    Each dict has keys: ref, alias, description, tools, hooks, context.
    """
    results: list[dict[str, Any]] = []
    visited: set[str] = set()

    queue: list[tuple[str, str]] = []  # (alias, ref)
    for b_dict in agent_def.behaviors:
        for alias, ref in b_dict.items():
            queue.append((alias, ref))

    while queue:
        alias, ref = queue.pop(0)
        if ref in visited:
            continue
        visited.add(ref)

        behavior_path: Path | None = None
        for lookup in [ref, alias]:
            try:
                behavior_path = registry.resolve_behavior(lookup)
                break
            except FileNotFoundError:
                continue

        if behavior_path is None:
            results.append(
                {
                    "ref": ref,
                    "alias": alias,
                    "description": "[dim]not found locally[/dim]",
                    "tools": False,
                    "hooks": False,
                    "context": False,
                }
            )
            continue

        bdef = parse_behavior_definition(behavior_path.read_text())
        bref = bdef.ref or ref
        results.append(
            {
                "ref": bref,
                "alias": alias,
                "description": bdef.description or "",
                "tools": bdef.tools,
                "hooks": bdef.hooks,
                "context": bdef.context,
            }
        )

        # Recurse into nested behaviors
        for nested_dict in bdef.behaviors:
            for nested_alias, nested_ref in nested_dict.items():
                if nested_ref not in visited:
                    queue.append((nested_alias, nested_ref))

    return results


# -- agents group -------------------------------------------------------------


@click.group(name="agents", invoke_without_command=True)
@click.pass_context
def agents(ctx: click.Context) -> None:
    """List and inspect registered agents."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# -- list ---------------------------------------------------------------------


@agents.command(name="list")
def list_agents() -> None:
    """List all registered agents."""
    registry = _get_registry()
    alias_map = _load_agents_alias_map(registry)
    names = _agent_ref_names(alias_map)

    if not names:
        console.print("[yellow]No agents registered.[/yellow]")
        console.print(
            "Run [bold]amplifier-ipc discover[/bold] or "
            "[bold]amplifier-ipc register[/bold] to add agents."
        )
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="green")
    table.add_column("Description", style="dim")
    table.add_column("Behaviors", style="cyan")
    table.add_column("Orchestrator", style="yellow")
    table.add_column("Provider", style="magenta")

    for name in sorted(names):
        description = "[dim]—[/dim]"
        behaviors_col = "[dim]—[/dim]"
        orchestrator_col = "[dim]—[/dim]"
        provider_col = "[dim]—[/dim]"

        try:
            agent_path = registry.resolve_agent(name)
            agent_def = parse_agent_definition(agent_path.read_text())
            description = agent_def.description or "[dim]—[/dim]"
            behaviors_col = _summarize_behaviors(agent_def)
            orchestrator_col = agent_def.orchestrator or "[dim]—[/dim]"
            provider_col = agent_def.provider or "[dim]—[/dim]"
        except FileNotFoundError:
            description = "[red]definition file missing[/red]"

        table.add_row(name, description, behaviors_col, orchestrator_col, provider_col)

    console.print(table)


# -- show ---------------------------------------------------------------------


@agents.command(name="show")
@click.argument("name")
def show_agent(name: str) -> None:
    """Show detailed information for agent NAME."""
    registry = _get_registry()

    try:
        agent_path = registry.resolve_agent(name)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    agent_def = parse_agent_definition(agent_path.read_text())

    # -- Basic info panel -----------------------------------------------------
    capability_flags: list[str] = []
    if agent_def.tools:
        capability_flags.append("tools")
    if agent_def.hooks:
        capability_flags.append("hooks")
    if agent_def.agents:
        capability_flags.append("sub-agents")
    if agent_def.context:
        capability_flags.append("context")

    basic_lines = [
        f"[bold]Name:[/bold]         {name}",
        f"[bold]Ref:[/bold]          {agent_def.ref or '[dim]—[/dim]'}",
        f"[bold]UUID:[/bold]         {agent_def.uuid or '[dim]—[/dim]'}",
        f"[bold]Version:[/bold]      {agent_def.version or '[dim]—[/dim]'}",
        f"[bold]Description:[/bold]  {agent_def.description or '[dim]—[/dim]'}",
        "",
        f"[bold]Orchestrator:[/bold]    {agent_def.orchestrator or '[dim]—[/dim]'}",
        f"[bold]Context Manager:[/bold] {agent_def.context_manager or '[dim]—[/dim]'}",
        f"[bold]Provider:[/bold]        {agent_def.provider or '[dim]—[/dim]'}",
        "",
        f"[bold]Capabilities:[/bold] {', '.join(capability_flags) or '[dim]none[/dim]'}",
    ]

    # Service info
    if agent_def.service is not None:
        svc = agent_def.service
        basic_lines += [
            "",
            "[bold]Service:[/bold]",
            f"  stack:   {svc.stack or '[dim]—[/dim]'}",
            f"  source:  {svc.source or '[dim]—[/dim]'}",
            f"  command: {svc.command or '[dim]—[/dim]'}",
        ]

    # Definition file
    basic_lines += ["", f"[bold]Definition file:[/bold] [dim]{agent_path}[/dim]"]

    console.print(
        Panel("\n".join(basic_lines), title=f"Agent: {name}", border_style="green")
    )

    # -- Behaviors panel ------------------------------------------------------
    behaviors = _walk_behaviors_summary(registry, agent_def, name)
    if behaviors:
        btable = Table(show_header=True, header_style="bold", title="Behaviors")
        btable.add_column("Alias", style="cyan")
        btable.add_column("Ref", style="green")
        btable.add_column("Description", style="dim")
        btable.add_column("Tools", style="yellow", justify="center")
        btable.add_column("Hooks", style="yellow", justify="center")
        btable.add_column("Context", style="yellow", justify="center")

        for binfo in behaviors:
            btable.add_row(
                binfo["alias"],
                binfo["ref"],
                binfo["description"] or "[dim]—[/dim]",
                "✓" if binfo["tools"] else "—",
                "✓" if binfo["hooks"] else "—",
                "✓" if binfo["context"] else "—",
            )

        console.print(btable)
    else:
        console.print("[dim]No behaviors declared.[/dim]")

    # -- Component config (if any) --------------------------------------------
    if agent_def.component_config:
        import json as _json

        config_text = _json.dumps(agent_def.component_config, indent=2)
        console.print(Panel(config_text, title="Component Config", border_style="dim"))
