"""First-run setup command for amplifier-ipc-cli.

Provides an interactive guided setup that checks agent registration, API keys,
and default configuration, then summarises the resulting state.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import click
import yaml
from rich.panel import Panel

from amplifier_ipc.cli.console import console
from amplifier_ipc.cli.key_manager import KeyManager
from amplifier_ipc.cli.provider_env_detect import detect_all_providers_from_env
from amplifier_ipc.cli.settings import get_settings
from amplifier_ipc.host.definition_registry import Registry
from amplifier_ipc.host.definitions import parse_agent_definition


# -- Known provider key mapping -----------------------------------------------

# Maps provider display name → primary env var name used in keys.env
_PROVIDER_KEY_NAMES: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "azure-openai": "AZURE_OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "github-copilot": "GITHUB_TOKEN",
    "ollama": "",  # no key needed
}

_PROVIDER_CHOICES = list(_PROVIDER_KEY_NAMES.keys())

# -- Module-level helpers (patchable) -----------------------------------------


def _get_registry() -> Registry:
    """Return a Registry instance (patchable for tests)."""
    return Registry()


def _get_key_manager() -> KeyManager:
    """Return a KeyManager instance (patchable for tests)."""
    return KeyManager()


def _get_settings() -> Any:
    """Return an AppSettings instance (patchable for tests)."""
    return get_settings()


# -- Internal helpers ---------------------------------------------------------


def _load_agent_names(registry: Registry) -> list[str]:
    """Return ref-style agent aliases from agents.yaml."""
    agents_yaml = registry.home / "agents.yaml"
    if not agents_yaml.exists():
        return []
    data: dict = yaml.safe_load(agents_yaml.read_text()) or {}
    return [k for k in data if "://" not in k]


def _has_any_key(km: KeyManager) -> bool:
    """Return True if at least one known provider key is in os.environ."""
    return any(
        km.has_key(env_var) for env_var in _PROVIDER_KEY_NAMES.values() if env_var
    )


def _keys_env_path() -> Path:
    """Return the path to the keys.env file."""
    return Path.home() / ".amplifier" / "keys.env"


def _describe_agent(registry: Registry, name: str) -> str:
    """Return a short description for an agent, or empty string."""
    try:
        path = registry.resolve_agent(name)
        adef = parse_agent_definition(path.read_text())
        return adef.description or ""
    except (FileNotFoundError, Exception):
        return ""


# -- Step helpers -------------------------------------------------------------


def _step_agents(
    registry: Registry,
    agent_names: list[str],
    reconfigure: bool,
) -> list[str]:
    """Handle the agents section of init.

    Returns the (possibly updated) agent list.
    """
    console.print("\n[bold]── Step 1: Agent Registration ──[/bold]")

    if agent_names and not reconfigure:
        console.print(
            f"[green]✓[/green] {len(agent_names)} agent(s) already registered: "
            + ", ".join(f"[cyan]{n}[/cyan]" for n in agent_names)
        )
        return agent_names

    if agent_names and reconfigure:
        console.print(
            "Current agents: " + ", ".join(f"[cyan]{n}[/cyan]" for n in agent_names)
        )

    console.print(
        "\n[yellow]No agents registered.[/yellow]\n"
        if not agent_names
        else "\nWould you like to register an additional agent?\n"
    )

    choices = (
        "\n  1. Discover agents from default location"
        "\n  2. Register a specific agent definition URL"
        "\n  3. Skip"
    )
    console.print(choices)

    choice = click.prompt(
        "Choice",
        type=click.Choice(["1", "2", "3"]),
        default="3",
        show_choices=False,
    )

    if choice == "1":
        console.print(
            "\n[dim]To discover agents, run:[/dim]\n"
            "  [bold]amplifier-ipc discover[/bold]\n"
            "or point discover at a URL:\n"
            "  [bold]amplifier-ipc discover --url <URL>[/bold]"
        )
    elif choice == "2":
        url = click.prompt("Agent definition URL or local file path")
        try:
            from amplifier_ipc.cli.commands.register import _register_from_source  # type: ignore[attr-defined]

            _register_from_source(url)
            console.print(f"[green]✓[/green] Agent registered from [cyan]{url}[/cyan].")
        except Exception:
            # Fall back to showing the manual command
            console.print(
                f"\n[dim]To register manually, run:[/dim]\n"
                f"  [bold]amplifier-ipc register {url}[/bold]"
            )
    # choice == "3": skip

    # Re-read after potential registration
    return _load_agent_names(registry)


def _step_api_keys(km: KeyManager) -> list[str]:
    """Handle the API keys section of init.

    Returns a list of provider names that ended up configured.
    """
    console.print("\n[bold]── Step 2: API Keys ──[/bold]")

    # Load keys from file so detection picks them up
    km.load_keys()

    detected = detect_all_providers_from_env()

    if detected:
        console.print("[green]✓[/green] Detected provider(s) from environment:")
        for provider, env_var in detected:
            console.print(f"  • [cyan]{provider}[/cyan] (via [dim]{env_var}[/dim])")

        if click.confirm(
            "\nSave detected key(s) to ~/.amplifier/keys.env?", default=True
        ):
            for provider, env_var in detected:
                value = os.environ.get(env_var, "")
                if value:
                    km.save_key(env_var, value)
                    console.print(
                        f"  [green]✓[/green] Saved [dim]{env_var}[/dim] for [cyan]{provider}[/cyan]."
                    )
        return [p for p, _ in detected]

    # No keys detected — offer to enter one manually
    console.print("[yellow]No API keys detected in environment.[/yellow]")

    if not click.confirm("\nWould you like to enter an API key now?", default=True):
        console.print(
            "[dim]You can add keys later with:[/dim]\n"
            "  [bold]amplifier-ipc provider set-key <PROVIDER>[/bold]"
        )
        return []

    # Show provider menu
    console.print("\nSupported providers:")
    for i, name in enumerate(_PROVIDER_CHOICES, 1):
        console.print(f"  {i}. {name}")

    idx = click.prompt(
        "Choose provider",
        type=click.IntRange(1, len(_PROVIDER_CHOICES)),
        default=1,
    )
    provider = _PROVIDER_CHOICES[idx - 1]
    env_var = _PROVIDER_KEY_NAMES.get(provider, "")

    if not env_var:
        console.print(f"[dim]{provider} requires no API key (runs locally).[/dim]")
        return [provider]

    # For azure-openai we also need the endpoint
    if provider == "azure-openai":
        endpoint = click.prompt("Azure OpenAI endpoint URL")
        km.save_key("AZURE_OPENAI_ENDPOINT", endpoint)
        console.print("[green]✓[/green] Saved AZURE_OPENAI_ENDPOINT.")

    api_key = click.prompt(f"API key for {provider}", hide_input=True)
    km.save_key(env_var, api_key)
    console.print(
        f"[green]✓[/green] Saved [dim]{env_var}[/dim] for [cyan]{provider}[/cyan]."
    )
    return [provider]


def _step_default_provider(
    settings: Any,
    configured_providers: list[str],
) -> None:
    """Offer to set a default provider if one isn't already configured."""
    console.print("\n[bold]── Step 3: Default Provider ──[/bold]")

    current = settings.get_provider()
    if current:
        console.print(
            f"[green]✓[/green] Default provider already set: [cyan]{current}[/cyan]"
        )
        return

    if not configured_providers:
        console.print("[dim]No providers configured — skipping.[/dim]")
        return

    if len(configured_providers) == 1:
        provider = configured_providers[0]
        if click.confirm(
            f"Set [cyan]{provider}[/cyan] as the default provider?", default=True
        ):
            settings.set_provider(provider)
            console.print(
                f"[green]✓[/green] Default provider set to [cyan]{provider}[/cyan]."
            )
        return

    console.print("Configured providers:")
    for i, p in enumerate(configured_providers, 1):
        console.print(f"  {i}. {p}")

    idx = click.prompt(
        "Set as default",
        type=click.IntRange(1, len(configured_providers)),
        default=1,
    )
    provider = configured_providers[idx - 1]
    settings.set_provider(provider)
    console.print(f"[green]✓[/green] Default provider set to [cyan]{provider}[/cyan].")


def _step_default_agent(
    settings: Any,
    registry: Registry,
    agent_names: list[str],
) -> None:
    """Offer to set a default agent in settings if none is configured."""
    console.print("\n[bold]── Step 4: Default Agent ──[/bold]")

    if not agent_names:
        console.print("[dim]No agents registered — skipping.[/dim]")
        return

    # Check if there is a "default_agent" setting already
    current = settings.get_merged_settings().get("default_agent")
    if current:
        console.print(
            f"[green]✓[/green] Default agent already set: [cyan]{current}[/cyan]"
        )
        return

    if len(agent_names) == 1:
        agent = agent_names[0]
        if click.confirm(
            f"Set [cyan]{agent}[/cyan] as the default agent?", default=True
        ):
            settings._update_setting("default_agent", agent)
            console.print(
                f"[green]✓[/green] Default agent set to [cyan]{agent}[/cyan]."
            )
        return

    console.print("Registered agents:")
    for i, name in enumerate(agent_names, 1):
        desc = _describe_agent(registry, name)
        suffix = f"  [dim]{desc}[/dim]" if desc else ""
        console.print(f"  {i}. [cyan]{name}[/cyan]{suffix}")

    idx = click.prompt(
        "Set as default agent",
        type=click.IntRange(1, len(agent_names)),
        default=1,
    )
    agent = agent_names[idx - 1]
    settings._update_setting("default_agent", agent)
    console.print(f"[green]✓[/green] Default agent set to [cyan]{agent}[/cyan].")


def _print_summary(
    registry: Registry,
    agent_names: list[str],
    configured_providers: list[str],
    settings: Any,
) -> None:
    """Print a final summary of the current setup."""
    console.print()

    merged = settings.get_merged_settings()
    default_provider = merged.get("provider", "[dim]not set[/dim]")
    default_agent = merged.get("default_agent", "[dim]not set[/dim]")
    keys_file = _keys_env_path()
    keys_status = (
        f"[green]{keys_file}[/green]" if keys_file.exists() else "[dim]not found[/dim]"
    )

    lines = [
        f"[bold]Agents registered:[/bold]  {len(agent_names)} "
        + (
            "(" + ", ".join(f"[cyan]{n}[/cyan]" for n in agent_names) + ")"
            if agent_names
            else ""
        ),
        "[bold]Providers detected:[/bold] "
        + (
            ", ".join(f"[cyan]{p}[/cyan]" for p in configured_providers)
            or "[dim]none[/dim]"
        ),
        f"[bold]Default provider:[/bold]   {default_provider}",
        f"[bold]Default agent:[/bold]      {default_agent}",
        f"[bold]Keys file:[/bold]          {keys_status}",
    ]

    next_steps: list[str] = []
    if not agent_names:
        next_steps.append(
            "  • Register an agent: [bold]amplifier-ipc register <URL>[/bold]"
        )
    if not configured_providers:
        next_steps.append(
            "  • Add an API key: [bold]amplifier-ipc provider set-key <PROVIDER>[/bold]"
        )
    if agent_names and configured_providers:
        default_a = merged.get("default_agent") or (
            agent_names[0] if agent_names else "<NAME>"
        )
        next_steps.append(
            f"  • Start a session: [bold]amplifier-ipc run --agent {default_a}[/bold]"
        )

    if next_steps:
        lines += ["", "[bold]Next steps:[/bold]"] + next_steps

    console.print(
        Panel("\n".join(lines), title="Amplifier Setup Summary", border_style="green")
    )


# -- Command ------------------------------------------------------------------


@click.command(name="init")
@click.option(
    "--reconfigure",
    is_flag=True,
    default=False,
    help="Re-run setup even if agents are already registered.",
)
def init_cmd(reconfigure: bool) -> None:
    """Interactive first-run setup for amplifier-ipc.

    Checks agent registration, API keys, and default configuration, then
    summarises the resulting state.  Safe to re-run at any time.
    """
    console.print(
        Panel(
            "Welcome to [bold]amplifier-ipc[/bold] setup.\n\n"
            "This wizard checks your configuration and helps you get started.",
            title="amplifier-ipc init",
            border_style="blue",
        )
    )

    registry = _get_registry()
    km = _get_key_manager()
    settings = _get_settings()

    # Step 1 — agents
    agent_names = _load_agent_names(registry)
    agent_names = _step_agents(registry, agent_names, reconfigure)

    # Step 2 — API keys
    configured_providers = _step_api_keys(km)

    # Step 3 — default provider
    _step_default_provider(settings, configured_providers)

    # Step 4 — default agent
    _step_default_agent(settings, registry, agent_names)

    # Summary
    _print_summary(registry, agent_names, configured_providers, settings)
