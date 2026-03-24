"""Provider management commands for amplifier-ipc-cli."""

from __future__ import annotations

import os

import click

from amplifier_ipc.cli.console import console
from amplifier_ipc.cli.key_manager import KeyManager
from amplifier_ipc.cli.provider_env_detect import detect_all_providers_from_env
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


# -- detect -------------------------------------------------------------------


@provider_group.command(name="detect")
def detect_providers() -> None:
    """Auto-detect available providers from environment variables."""
    detected = detect_all_providers_from_env()
    if not detected:
        console.print(
            "[yellow]No providers detected.[/yellow]\n"
            "Set an API key: [dim]export ANTHROPIC_API_KEY=sk-...[/dim]\n"
            "Or use: [dim]amplifier-ipc provider set-key anthropic[/dim]"
        )
        return

    console.print(f"Detected {len(detected)} provider(s):\n")
    for provider_name, env_var in detected:
        console.print(f"  [green]{provider_name}[/green]  (from {env_var})")

    # Suggest setting the first one as default if none is configured
    settings = _get_settings()
    current = settings.get_provider()
    if not current:
        first = detected[0][0].replace("-", "_")
        console.print(
            f"\n[dim]Tip: set a default with:[/dim] "
            f"[cyan]amplifier-ipc provider use {first}[/cyan]"
        )


# -- configure ----------------------------------------------------------------


# Known provider config fields — loaded from provider class metadata at runtime
# via the describe protocol.  This static fallback is used when the service
# isn't running (i.e., during offline CLI configuration).
_PROVIDER_CONFIG_FIELDS: dict[str, list[dict[str, str]]] = {
    "anthropic": [
        {
            "id": "api_key",
            "type": "secret",
            "env": "ANTHROPIC_API_KEY",
            "desc": "API key",
        },
        {
            "id": "model",
            "type": "text",
            "desc": "Model name",
            "default": "claude-sonnet-4-20250514",
        },
        {
            "id": "max_tokens",
            "type": "number",
            "desc": "Max output tokens",
            "default": "16384",
        },
        {"id": "temperature", "type": "number", "desc": "Temperature (0.0-1.0)"},
    ],
    "openai": [
        {"id": "api_key", "type": "secret", "env": "OPENAI_API_KEY", "desc": "API key"},
        {"id": "model", "type": "text", "desc": "Model name", "default": "gpt-4o"},
        {
            "id": "max_tokens",
            "type": "number",
            "desc": "Max output tokens",
            "default": "16384",
        },
        {"id": "temperature", "type": "number", "desc": "Temperature (0.0-1.0)"},
    ],
    "azure_openai": [
        {
            "id": "api_key",
            "type": "secret",
            "env": "AZURE_OPENAI_API_KEY",
            "desc": "API key",
        },
        {
            "id": "azure_endpoint",
            "type": "text",
            "env": "AZURE_OPENAI_ENDPOINT",
            "desc": "Azure endpoint URL",
        },
        {
            "id": "api_version",
            "type": "text",
            "desc": "API version",
            "default": "2024-12-01-preview",
        },
        {"id": "model", "type": "text", "desc": "Deployment / model name"},
    ],
    "gemini": [
        {"id": "api_key", "type": "secret", "env": "GOOGLE_API_KEY", "desc": "API key"},
        {
            "id": "model",
            "type": "text",
            "desc": "Model name",
            "default": "gemini-2.0-flash",
        },
        {
            "id": "max_tokens",
            "type": "number",
            "desc": "Max output tokens",
            "default": "8192",
        },
    ],
    "ollama": [
        {
            "id": "host",
            "type": "text",
            "env": "OLLAMA_HOST",
            "desc": "Ollama host URL",
            "default": "http://localhost:11434",
        },
        {"id": "model", "type": "text", "desc": "Model name", "default": "llama3.2"},
    ],
    "vllm": [
        {
            "id": "base_url",
            "type": "text",
            "env": "VLLM_API_BASE",
            "desc": "vLLM server URL",
        },
        {
            "id": "api_key",
            "type": "secret",
            "env": "VLLM_API_KEY",
            "desc": "API key (optional)",
        },
        {"id": "model", "type": "text", "desc": "Model name"},
    ],
    "github_copilot": [
        {
            "id": "token",
            "type": "secret",
            "env": "GITHUB_TOKEN",
            "desc": "GitHub token",
        },
        {"id": "model", "type": "text", "desc": "Model name", "default": "gpt-4o"},
    ],
}


@provider_group.command(name="configure")
@click.argument("provider")
def configure_provider(provider: str) -> None:
    """Interactively configure PROVIDER settings.

    Walks through each configuration field (API key, model, temperature, etc.)
    and saves the values.  Secret fields are prompted securely.  Press Enter
    to accept the default or skip optional fields.
    """
    fields = _PROVIDER_CONFIG_FIELDS.get(provider)
    if not fields:
        known = ", ".join(sorted(_PROVIDER_CONFIG_FIELDS))
        raise click.ClickException(
            f"Unknown provider: {provider}\nKnown providers: {known}"
        )

    console.print(f"\n[bold]Configure {provider}[/bold]\n")

    settings = _get_settings()
    km = _get_key_manager()
    override_config: dict[str, str] = {}

    for field in fields:
        fid = field["id"]
        ftype = field.get("type", "text")
        desc = field.get("desc", fid)
        default = field.get("default", "")
        env_var = field.get("env")

        # Show current value (from env or default)
        current = ""
        if env_var:
            current = os.environ.get(env_var, "")
        hint = f" [dim](current: {current[:8]}...)[/dim]" if current else ""
        if default and not current:
            hint = f" [dim](default: {default})[/dim]"

        if ftype == "secret":
            console.print(f"  {desc}{hint}")
            value = click.prompt(
                f"  {fid}", default="", hide_input=True, show_default=False
            )
            if value:
                key_name = env_var or f"{provider.upper()}_{fid.upper()}"
                km.save_key(key_name, value)
                console.print(f"    [green]Saved to keys.env as {key_name}[/green]")
        else:
            value = click.prompt(
                f"  {desc}", default=default or "", show_default=bool(default)
            )
            if value and value != default:
                override_config[fid] = value

    # Save non-secret overrides to settings
    if override_config:
        override_config["provider"] = provider
        settings.set_provider_override(override_config)
        console.print(f"\n[green]Configuration saved for {provider}.[/green]")

    # Offer to set as default
    current_default = settings.get_provider()
    if current_default != provider:
        if click.confirm(f"\nSet {provider} as the default provider?", default=True):
            settings.set_provider(provider)
            console.print(f"Default provider set to [green]{provider}[/green].")
