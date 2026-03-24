"""Tool management commands for amplifier-ipc-cli.

Provides CLI subcommands for listing, inspecting, and invoking agent tools
from the amplifier definition registry.
"""

from __future__ import annotations

import asyncio
import json
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


def _get_all_agent_names(registry: Registry) -> list[str]:
    """Return all agent ref aliases from agents.yaml (excludes URL keys)."""
    agents_yaml = registry.home / "agents.yaml"
    if not agents_yaml.exists():
        return []
    data: dict = yaml.safe_load(agents_yaml.read_text()) or {}
    # Only ref aliases — skip URL-shaped keys (contain "://")
    return [k for k in data if "://" not in k]


def _collect_tool_services(
    registry: Registry,
    agent_name: str,
) -> list[dict[str, Any]]:
    """Walk an agent's behavior tree and collect entries that claim tools.

    Returns a list of dicts with keys:
        ref         — the behavior/agent ref
        kind        — "agent" or "behavior"
        description — human-readable description (may be empty)
    """
    results: list[dict[str, Any]] = []
    visited: set[str] = set()

    try:
        agent_path = registry.resolve_agent(agent_name)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    agent_def = parse_agent_definition(agent_path.read_text())
    agent_ref = agent_def.ref or agent_name

    if agent_def.tools:
        results.append(
            {
                "ref": agent_ref,
                "kind": "agent",
                "description": agent_def.description or "",
            }
        )

    # BFS over behavior tree
    queue: list[tuple[str, str]] = []  # (alias, ref)
    for b_dict in agent_def.behaviors:
        for alias, ref in b_dict.items():
            queue.append((alias, ref))

    while queue:
        alias, ref = queue.pop(0)
        if ref in visited:
            continue
        visited.add(ref)

        behavior_path = None
        for lookup in [ref, alias]:
            try:
                behavior_path = registry.resolve_behavior(lookup)
                break
            except FileNotFoundError:
                continue

        if behavior_path is None:
            continue

        bdef = parse_behavior_definition(behavior_path.read_text())
        bref = bdef.ref or ref

        if bdef.tools:
            results.append(
                {
                    "ref": bref,
                    "kind": "behavior",
                    "description": bdef.description or "",
                }
            )

        for nested_dict in bdef.behaviors:
            for nested_alias, nested_ref in nested_dict.items():
                if nested_ref not in visited:
                    queue.append((nested_alias, nested_ref))

    return results


# -- tool group ---------------------------------------------------------------


@click.group(name="tool", invoke_without_command=True)
@click.pass_context
def tool(ctx: click.Context) -> None:
    """Manage and invoke agent tools."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# -- list ---------------------------------------------------------------------


@tool.command(name="list")
@click.option(
    "--agent",
    "-a",
    default=None,
    help="Agent name to inspect (default: all registered agents).",
)
def list_tools(agent: str | None) -> None:
    """List services that provide tools, optionally filtered by agent."""
    registry = _get_registry()

    if agent is not None:
        agent_names = [agent]
    else:
        agent_names = _get_all_agent_names(registry)

    if not agent_names:
        console.print("[yellow]No agents registered.[/yellow]")
        console.print(
            "Run [bold]amplifier-ipc discover[/bold] or "
            "[bold]amplifier-ipc register[/bold] to add agents."
        )
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Agent", style="green")
    table.add_column("Service / Behavior", style="cyan")
    table.add_column("Kind", style="yellow")
    table.add_column("Description", style="dim")

    found_any = False
    for agent_name in agent_names:
        try:
            entries = _collect_tool_services(registry, agent_name)
        except click.ClickException as exc:
            console.print(
                f"[red]Error resolving agent '{agent_name}': {exc.format_message()}[/red]"
            )
            continue

        for entry in entries:
            found_any = True
            table.add_row(
                agent_name,
                entry["ref"],
                entry["kind"],
                entry["description"] or "[dim]—[/dim]",
            )

    if not found_any:
        console.print("[dim]No tool-providing services found.[/dim]")
        console.print(
            "\n[dim]Note: tool names and schemas are only available from a running "
            "session. Start a session with [bold]amplifier-ipc run --agent <NAME>[/bold]"
            " to use tools interactively.[/dim]"
        )
        return

    console.print(table)
    console.print(
        "\n[dim]Note: individual tool names and schemas require a running session. "
        "Use [bold]amplifier-ipc tool info <TOOL>[/bold] for best-effort static info.[/dim]"
    )


# -- info ---------------------------------------------------------------------


@tool.command(name="info")
@click.argument("tool_name")
@click.option(
    "--agent",
    "-a",
    default=None,
    help="Agent name to search (default: all registered agents).",
)
def tool_info(tool_name: str, agent: str | None) -> None:
    """Show info for TOOL_NAME.

    Searches the static definition tree for the tool. Full parameter schemas
    are only available from a running session because they come from each
    service's runtime describe response.
    """
    registry = _get_registry()

    if agent is not None:
        agent_names = [agent]
    else:
        agent_names = _get_all_agent_names(registry)

    if not agent_names:
        raise click.ClickException(
            "No agents registered. Run discover or register first."
        )

    # Walk each agent and collect all tool-providing services; display what we know.
    found: list[dict[str, Any]] = []
    for agent_name in agent_names:
        try:
            entries = _collect_tool_services(registry, agent_name)
        except click.ClickException:
            continue
        for entry in entries:
            # We can't match individual tool names statically — report all
            # tool-providing services as potential matches.
            found.append({"agent": agent_name, **entry})

    if not found:
        raise click.ClickException(
            f"No tool-providing services found for tool '{tool_name}'. "
            "Ensure the agent is registered and has tool-providing behaviors."
        )

    lines = [
        f"[bold]Tool:[/bold] {tool_name}",
        "",
        "[bold]Potential source services[/bold] (services that advertise tools):",
    ]
    for entry in found:
        lines.append(
            f"  • [cyan]{entry['ref']}[/cyan] ({entry['kind']}) "
            f"from agent [green]{entry['agent']}[/green]"
        )
        if entry.get("description"):
            lines.append(f"    {entry['description']}")

    lines += [
        "",
        "[dim]Full parameter schema is only available from a running session.[/dim]",
        "[dim]The service's describe response contains the JSON schema for each tool.[/dim]",
        "[dim]Start a session with [bold]amplifier-ipc run --agent <NAME>[/bold] to use tools.[/dim]",
    ]

    panel = Panel("\n".join(lines), title=f"Tool: {tool_name}", border_style="blue")
    console.print(panel)


# -- invoke -------------------------------------------------------------------


async def _invoke_tool(
    agent_name: str,
    tool_name: str,
    params: dict[str, Any],
) -> None:
    """Async implementation: launch a session and invoke a tool directly."""
    from amplifier_ipc.cli.key_manager import KeyManager
    from amplifier_ipc.cli.session_launcher import launch_session
    from amplifier_ipc.host.events import ApprovalRequestEvent

    km = KeyManager()
    km.load_keys()

    console.print(f"Launching session for agent [green]{agent_name}[/green]…")
    host = await launch_session(agent_name)

    # Build a natural-language instruction for the agent.
    if params:
        param_str = ", ".join(f"{k}={json.dumps(v)}" for k, v in params.items())
        message = f"Please call the tool `{tool_name}` with these parameters: {param_str}. Return only the raw result."
    else:
        message = f"Please call the tool `{tool_name}` with no parameters. Return only the raw result."

    console.print(f"Invoking [cyan]{tool_name}[/cyan]…\n")

    from amplifier_ipc.cli.repl import handle_host_event

    async for event in host.run(message):
        if isinstance(event, ApprovalRequestEvent):
            host.send_approval(True)
        else:
            handle_host_event(event)


def _parse_kv_arg(arg: str) -> tuple[str, Any]:
    """Parse a key=value argument, auto-detecting JSON values.

    Examples:
        foo=bar        → ("foo", "bar")
        count=42       → ("count", 42)
        flag=true      → ("flag", True)
        data={"x":1}   → ("data", {"x": 1})
    """
    if "=" not in arg:
        raise click.BadParameter(
            f"Expected key=value format, got: {arg!r}",
            param_hint="PARAMS",
        )
    key, _, raw = arg.partition("=")
    key = key.strip()
    raw = raw.strip()

    # Try JSON decode first (handles numbers, booleans, objects, arrays)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw  # treat as plain string

    return key, value


@tool.command(name="invoke")
@click.argument("tool_name")
@click.argument("params", nargs=-1, metavar="[key=value ...]")
@click.option(
    "--agent",
    "-a",
    required=True,
    help="Agent name to use for invocation.",
)
def invoke_tool(
    tool_name: str,
    params: tuple[str, ...],
    agent: str,
) -> None:
    """Invoke TOOL_NAME via an agent session.

    Accepts optional key=value parameters. JSON values are auto-detected:
    numbers, booleans (true/false), objects, and arrays are parsed
    automatically; everything else is treated as a string.

    Example:
        amplifier-ipc tool invoke read_file path=/tmp/foo.txt --agent myagent
    """
    parsed_params: dict[str, Any] = {}
    for raw_arg in params:
        k, v = _parse_kv_arg(raw_arg)
        parsed_params[k] = v

    asyncio.run(_invoke_tool(agent, tool_name, parsed_params))
