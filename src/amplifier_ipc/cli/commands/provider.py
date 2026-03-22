"""Provider management commands for amplifier-ipc-cli."""

from __future__ import annotations

import click

from amplifier_ipc.cli.console import console
from amplifier_ipc.cli.key_manager import KeyManager
from amplifier_ipc.cli.settings import AppSettings, get_settings

# -- Module-level helpers (patchable) -----------------------------------------


def _get_settings() -> AppSettings:
    """Return an AppSettings instance (patchable for tests)."""
    return get_settings()


def _get_key_manager() -> KeyManager:
    """Return a KeyManager instance (patchable for tests)."""
    return KeyManager()


# -- Provider group -----------------------------------------------------------


@click.group(name="provider", invoke_without_command=True)
@click.pass_context
def provider_group(ctx: click.Context) -> None:
    """Manage provider configuration."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# -- list ---------------------------------------------------------------------


@provider_group.command(name="list")
def list_providers() -> None:
    """Show the current provider and any overrides."""
    settings = _get_settings()
    provider = settings.get_provider()
    overrides = settings.get_provider_overrides()

    if provider:
        console.print(f"Default provider: [green]{provider}[/green]")
    else:
        console.print("Default provider: [dim]not set[/dim]")

    if overrides:
        console.print("\nProvider overrides:")
        for override in overrides:
            prov = override.get("provider", "<unknown>")
            model = override.get("model", "")
            if model:
                console.print(f"  [cyan]{prov}[/cyan] → [yellow]{model}[/yellow]")
            else:
                console.print(f"  [cyan]{prov}[/cyan]")
    else:
        console.print("No provider overrides configured.")


# -- set-key ------------------------------------------------------------------


@provider_group.command(name="set-key")
@click.argument("provider")
def set_key(provider: str) -> None:
    """Set the API key for PROVIDER.

    Prompts for the API key securely and saves it via KeyManager.
    """
    key_name = f"{provider.upper()}_API_KEY"
    api_key = click.prompt(f"API key for {provider}", hide_input=True)
    km = _get_key_manager()
    km.save_key(key_name, api_key)
    console.print(f"API key for [green]{provider}[/green] saved.")


# -- use ----------------------------------------------------------------------


@provider_group.command(name="use")
@click.argument("provider")
@click.option("--model", default=None, help="Optional model to use with this provider.")
def use_provider(provider: str, model: str | None) -> None:
    """Set PROVIDER as the default provider (optionally with MODEL)."""
    settings = _get_settings()
    settings.set_provider(provider)
    if model:
        settings.set_provider_override({"provider": provider, "model": model})
        console.print(
            f"Default provider set to [green]{provider}[/green] "
            f"with model [yellow]{model}[/yellow]."
        )
    else:
        console.print(f"Default provider set to [green]{provider}[/green].")
