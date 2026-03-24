"""Routing matrix management commands for amplifier-ipc-cli."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import yaml

from amplifier_ipc.cli.console import console
from amplifier_ipc.cli.settings import AppSettings, get_settings

# -- Module-level helpers (patchable) -----------------------------------------

_ROUTING_DIR = Path("~/.amplifier/routing")

# Standard roles for interactive matrix creation
_STANDARD_ROLES = ["general", "fast", "coding", "reasoning", "creative", "writing"]


def _get_settings() -> AppSettings:
    """Return an AppSettings instance (patchable for tests)."""
    return get_settings()


def _get_routing_dir() -> Path:
    """Return the routing directory path (patchable for tests)."""
    return _ROUTING_DIR.expanduser()


def _count_roles(data: Any) -> int:
    """Return the number of roles defined in a routing matrix data dict."""
    if not isinstance(data, dict):
        return 0
    roles = data.get("roles", {})
    if not isinstance(roles, dict):
        return 0
    return len(roles)


def _load_matrix(yaml_path: Path) -> dict[str, Any] | None:
    """Load a routing matrix YAML; return None on failure."""
    try:
        raw = yaml_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


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
    """List available routing matrix YAML files in ~/.amplifier/routing/.

    Shows the active matrix with an asterisk and displays the number of
    roles defined in each matrix.
    """
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
        data = _load_matrix(yaml_file)
        role_count = _count_roles(data)
        description = ""
        if data:
            desc = data.get("description", "")
            if desc:
                description = f" — [dim]{desc}[/dim]"

        roles_label = f"[dim]{role_count} roles[/dim]"

        if name == active_matrix:
            console.print(
                f"  [green]* {name}[/green] (active)  {roles_label}{description}"
            )
        else:
            console.print(f"    {name}  {roles_label}{description}")


# -- show ---------------------------------------------------------------------


@routing_group.command(name="show")
@click.argument("name")
@click.option(
    "--detailed",
    "-d",
    is_flag=True,
    default=False,
    help="Show the full waterfall of candidates per role.",
)
def show_matrix(name: str, detailed: bool) -> None:
    """Display roles from the routing matrix YAML file NAME.

    Use --detailed to show all candidates per role in priority order.
    """
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

    description = data.get("description", "")
    updated = data.get("updated", "")
    header_parts = [f"[bold]Routing matrix:[/bold] {name}"]
    if description:
        header_parts.append(f"[dim]{description}[/dim]")
    if updated:
        header_parts.append(f"[dim]updated {updated}[/dim]")
    console.print("\n".join(header_parts) + "\n")

    roles = data.get("roles", {})
    if not isinstance(roles, dict):
        console.print("[dim]No roles defined.[/dim]")
        return

    for role, config in roles.items():
        if not isinstance(config, dict):
            console.print(f"  [cyan]{role}[/cyan]: {config}")
            continue

        role_desc = config.get("description", "")
        candidates = config.get("candidates", [])
        provider = config.get("provider", "?")
        model = config.get("model", "?")

        if detailed and isinstance(candidates, list) and candidates:
            # Show full candidate waterfall
            label = f"[cyan]{role}[/cyan]"
            if role_desc:
                label += f" [dim]— {role_desc}[/dim]"
            console.print(f"  {label}")
            for idx, candidate in enumerate(candidates, start=1):
                if isinstance(candidate, dict):
                    cprov = candidate.get("provider", "?")
                    cmodel = candidate.get("model", "?")
                    cconfig = candidate.get("config", {})
                    line = f"    [dim]{idx}.[/dim] {cprov} / {cmodel}"
                    if cconfig:
                        config_str = ", ".join(f"{k}={v}" for k, v in cconfig.items())
                        line += f" [dim]({config_str})[/dim]"
                    console.print(line)
                else:
                    console.print(f"    [dim]{idx}.[/dim] {candidate}")
        elif isinstance(candidates, list) and candidates:
            # Show primary candidate only
            first = candidates[0] if candidates else {}
            if isinstance(first, dict):
                provider = first.get("provider", "?")
                model = first.get("model", "?")
            extra = (
                f" [dim]+{len(candidates) - 1} fallback(s)[/dim]"
                if len(candidates) > 1
                else ""
            )
            console.print(f"  [cyan]{role}[/cyan]: {provider} / {model}{extra}")
        else:
            # Legacy single-entry format
            console.print(f"  [cyan]{role}[/cyan]: {provider} / {model}")


# -- use ----------------------------------------------------------------------


@routing_group.command(name="use")
@click.argument("name")
def use_matrix(name: str) -> None:
    """Set NAME as the active routing matrix."""
    settings = _get_settings()
    settings.set_routing_matrix(name)
    console.print(f"Active routing matrix set to [green]{name}[/green].")


# -- manage -------------------------------------------------------------------


@routing_group.command(name="manage")
def manage_matrices() -> None:
    """Interactively browse, inspect, and activate routing matrices.

    Shows a numbered list of available matrices. Enter a number to select
    one, then choose to view details or activate it.
    """
    settings = _get_settings()
    routing_dir = _get_routing_dir()

    if not routing_dir.exists():
        console.print("No routing directory found at [dim]~/.amplifier/routing/[/dim].")
        return

    yaml_files = sorted(routing_dir.glob("*.yaml"))
    if not yaml_files:
        console.print("No routing matrix files found.")
        return

    while True:
        routing_config = settings.get_routing_config()
        active_matrix = routing_config.get("active_matrix")

        console.print("\n[bold]Routing Matrices[/bold]\n")
        for idx, yaml_file in enumerate(yaml_files, start=1):
            name = yaml_file.stem
            data = _load_matrix(yaml_file)
            role_count = _count_roles(data)
            desc = ""
            if data:
                d = data.get("description", "")
                if d:
                    desc = f" — [dim]{d[:60]}[/dim]"
            active_marker = " [green](active)[/green]" if name == active_matrix else ""
            console.print(
                f"  [dim]{idx:>2}.[/dim] [cyan]{name}[/cyan]{active_marker}"
                f"  [dim]{role_count} roles[/dim]{desc}"
            )

        console.print("\n[dim]  Enter number to select, q to quit[/dim]")

        try:
            raw = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Exiting.[/dim]")
            sys.exit(0)

        if raw == "q":
            console.print("[dim]Exiting.[/dim]")
            return

        try:
            choice = int(raw)
        except ValueError:
            console.print("[red]Invalid input. Enter a number or q.[/red]")
            continue

        if not (1 <= choice <= len(yaml_files)):
            console.print(
                f"[red]Please enter a number between 1 and {len(yaml_files)}.[/red]"
            )
            continue

        selected_file = yaml_files[choice - 1]
        selected_name = selected_file.stem
        data = _load_matrix(selected_file)
        role_count = _count_roles(data)
        desc = data.get("description", "") if data else ""

        console.print(
            f"\nSelected: [cyan]{selected_name}[/cyan]  [dim]{role_count} roles[/dim]"
        )
        if desc:
            console.print(f"[dim]{desc}[/dim]")

        console.print("\n  [dim]v[/dim] view details")
        console.print("  [dim]a[/dim] activate")
        console.print("  [dim]b[/dim] back to list")

        try:
            action = input("  action> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Exiting.[/dim]")
            sys.exit(0)

        if action == "v":
            # Show matrix details inline
            console.print("")
            if data:
                roles = data.get("roles", {})
                if isinstance(roles, dict):
                    for role, rconfig in roles.items():
                        if isinstance(rconfig, dict):
                            candidates = rconfig.get("candidates", [])
                            if isinstance(candidates, list) and candidates:
                                first = candidates[0]
                                prov = (
                                    first.get("provider", "?")
                                    if isinstance(first, dict)
                                    else "?"
                                )
                                mod = (
                                    first.get("model", "?")
                                    if isinstance(first, dict)
                                    else "?"
                                )
                                extra = (
                                    f" [dim]+{len(candidates) - 1}[/dim]"
                                    if len(candidates) > 1
                                    else ""
                                )
                                console.print(
                                    f"  [cyan]{role}[/cyan]: {prov} / {mod}{extra}"
                                )
                            else:
                                prov = rconfig.get("provider", "?")
                                mod = rconfig.get("model", "?")
                                console.print(f"  [cyan]{role}[/cyan]: {prov} / {mod}")
                        else:
                            console.print(f"  [cyan]{role}[/cyan]: {rconfig}")
                else:
                    console.print("[dim]No roles defined.[/dim]")
            else:
                console.print("[red]Could not load matrix file.[/red]")

        elif action == "a":
            settings.set_routing_matrix(selected_name)
            console.print(
                f"[green]✓[/green] Active matrix set to [green]{selected_name}[/green]."
            )

        elif action == "b":
            continue
        else:
            console.print("[dim]Unknown action. Returning to list.[/dim]")


# -- create -------------------------------------------------------------------


@routing_group.command(name="create")
@click.option(
    "--name",
    "-n",
    "matrix_name",
    default=None,
    help="Name for the new routing matrix (skips interactive prompt).",
)
@click.option(
    "--clone",
    default=None,
    metavar="EXISTING_NAME",
    help="Clone an existing matrix as the starting point.",
)
def create_matrix(matrix_name: str | None, clone: str | None) -> None:
    """Interactively create a new routing matrix YAML file.

    Prompts for a name, optional description, and provider/model assignments
    for each of the standard roles (general, fast, coding, reasoning,
    creative, writing).

    The resulting file is saved to ~/.amplifier/routing/<name>.yaml.
    """
    routing_dir = _get_routing_dir()
    routing_dir.mkdir(parents=True, exist_ok=True)

    # --- name ----------------------------------------------------------------
    if matrix_name is None:
        try:
            matrix_name = input("Matrix name: ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Cancelled.[/dim]")
            sys.exit(0)

    if not matrix_name:
        raise click.ClickException("Matrix name cannot be empty.")

    if "/" in matrix_name or "\\" in matrix_name or matrix_name.startswith("."):
        raise click.ClickException(
            "Matrix name cannot contain '/' or '\\' and cannot start with '.'."
        )

    output_path = routing_dir / f"{matrix_name}.yaml"
    if output_path.exists():
        try:
            overwrite = (
                input(f"Matrix '{matrix_name}' already exists. Overwrite? [y/N] ")
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Cancelled.[/dim]")
            sys.exit(0)
        if overwrite not in ("y", "yes"):
            console.print("[dim]Cancelled.[/dim]")
            return

    # --- description ---------------------------------------------------------
    try:
        description = input("Description (optional): ").strip()
    except (EOFError, KeyboardInterrupt):
        description = ""

    # --- clone base ----------------------------------------------------------
    base_roles: dict[str, Any] = {}
    if clone is not None:
        clone_path = routing_dir / f"{clone}.yaml"
        if not clone_path.exists():
            raise click.ClickException(f"Matrix to clone not found: {clone}")
        base_data = _load_matrix(clone_path)
        if base_data and isinstance(base_data.get("roles"), dict):
            base_roles = dict(base_data["roles"])
            console.print(f"[dim]Cloned {len(base_roles)} roles from '{clone}'.[/dim]")

    # --- per-role assignments ------------------------------------------------
    console.print("\n[bold]Assign provider and model for each standard role.[/bold]")
    console.print(
        "[dim]Press Enter to keep existing value (shown in brackets).[/dim]\n"
    )

    roles: dict[str, Any] = {}
    for role in _STANDARD_ROLES:
        existing = base_roles.get(role)
        existing_candidates = (
            existing.get("candidates", []) if isinstance(existing, dict) else []
        )
        default_provider = ""
        default_model = ""
        if existing_candidates and isinstance(existing_candidates[0], dict):
            default_provider = existing_candidates[0].get("provider", "")
            default_model = existing_candidates[0].get("model", "")

        prov_prompt = f"  {role} — provider"
        if default_provider:
            prov_prompt += f" [{default_provider}]"
        prov_prompt += ": "

        try:
            provider = input(prov_prompt).strip() or default_provider
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Cancelled.[/dim]")
            sys.exit(0)

        if not provider:
            console.print(f"  [dim]Skipping {role} (no provider given).[/dim]")
            if existing is not None:
                roles[role] = existing
            continue

        mod_prompt = f"  {role} — model"
        if default_model:
            mod_prompt += f" [{default_model}]"
        mod_prompt += ": "

        try:
            model = input(mod_prompt).strip() or default_model
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Cancelled.[/dim]")
            sys.exit(0)

        if not model:
            console.print(f"  [dim]Skipping {role} (no model given).[/dim]")
            if existing is not None:
                roles[role] = existing
            continue

        roles[role] = {
            "candidates": [
                {"provider": provider, "model": model},
            ],
        }

    if not roles:
        console.print("[yellow]No roles defined. Aborting.[/yellow]")
        return

    # --- build and write YAML ------------------------------------------------
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    matrix_data: dict[str, Any] = {
        "name": matrix_name,
        "description": description or f"Custom routing matrix '{matrix_name}'.",
        "updated": today,
        "roles": roles,
    }

    header = (
        f"# Routing Matrix: {matrix_name}\n"
        "#\n"
        "# Created by amplifier-ipc routing create.\n"
        "# Edit candidates lists to add fallback models.\n"
        "#\n\n"
    )

    yaml_text = header + yaml.dump(
        matrix_data, default_flow_style=False, sort_keys=False
    )
    output_path.write_text(yaml_text, encoding="utf-8")

    console.print(
        f"\n[green]✓[/green] Matrix '[cyan]{matrix_name}[/cyan]' saved to "
        f"[dim]{output_path}[/dim]"
    )
    console.print(
        f"  Defined [yellow]{len(roles)}[/yellow] roles: " + ", ".join(roles.keys())
    )
    console.print(
        f"\nActivate with: [bold]amplifier-ipc routing use {matrix_name}[/bold]"
    )
