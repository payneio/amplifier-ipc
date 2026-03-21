"""Notification configuration commands for amplifier-ipc-cli."""

from __future__ import annotations

from typing import Any

import click
from rich.table import Table

from amplifier_ipc_cli.console import console
from amplifier_ipc_cli.key_manager import KeyManager
from amplifier_ipc_cli.settings import AppSettings, get_settings

# -- Constants -----------------------------------------------------------------

NTFY_TOPIC_ENV_VAR = "AMPLIFIER_NTFY_TOPIC"

# -- Module-level helpers (patchable) -----------------------------------------


def _get_settings() -> AppSettings:
    """Return an AppSettings instance (patchable for tests)."""
    return get_settings()


def _get_key_manager() -> KeyManager:
    """Return a KeyManager instance (patchable for tests)."""
    return KeyManager()


# -- Notify group --------------------------------------------------------------


@click.group(name="notify", invoke_without_command=True)
@click.pass_context
def notify_group(ctx: click.Context) -> None:
    """Manage notification settings."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# -- status -------------------------------------------------------------------


@notify_group.command(name="status")
def status() -> None:
    """Show current notification configuration."""
    settings = _get_settings()
    km = _get_key_manager()
    config = settings.get_notification_config()

    if not config:
        console.print("No notifications configured.")
        return

    table = Table(title="Notification Settings")
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    desktop_cfg: dict[str, Any] = config.get("desktop", {})
    if desktop_cfg:
        table.add_row("desktop.enabled", str(desktop_cfg.get("enabled", False)))
        for sub_key in (
            "show_device",
            "show_project",
            "show_preview",
            "preview_length",
        ):
            if sub_key in desktop_cfg:
                table.add_row(f"desktop.{sub_key}", str(desktop_cfg[sub_key]))

    ntfy_cfg: dict[str, Any] = config.get("ntfy", {})
    if ntfy_cfg:
        table.add_row("ntfy.enabled", str(ntfy_cfg.get("enabled", False)))
        topic_status = "configured" if km.has_key(NTFY_TOPIC_ENV_VAR) else "not set"
        table.add_row("ntfy.topic", topic_status)

    console.print(table)


# -- desktop ------------------------------------------------------------------


@notify_group.command(name="desktop")
@click.option("--enable", "action", flag_value="enable", default=None)
@click.option("--disable", "action", flag_value="disable")
def desktop_cmd(action: str | None) -> None:
    """Configure desktop notifications."""
    settings = _get_settings()
    config = settings.get_notification_config()
    desktop_cfg: dict[str, Any] = dict(config.get("desktop", {}))

    if action is None:
        # Show current config
        if not desktop_cfg:
            console.print("Desktop notifications: not configured.")
        else:
            enabled = desktop_cfg.get("enabled", False)
            console.print(
                f"Desktop notifications: {'enabled' if enabled else 'disabled'}"
            )
        return

    enabled = action == "enable"
    desktop_cfg["enabled"] = enabled
    settings.set_notification_config("desktop", desktop_cfg, scope="global")
    console.print(f"Desktop notifications {'enabled' if enabled else 'disabled'}.")


# -- ntfy ---------------------------------------------------------------------


@notify_group.command(name="ntfy")
@click.option("--enable", "action", flag_value="enable", default=None)
@click.option("--disable", "action", flag_value="disable")
@click.option("--server", default=None, help="ntfy.sh server URL.")
def ntfy_cmd(action: str | None, server: str | None) -> None:
    """Configure ntfy.sh push notifications."""
    settings = _get_settings()
    km = _get_key_manager()
    config = settings.get_notification_config()
    ntfy_cfg: dict[str, Any] = dict(config.get("ntfy", {}))

    if action is None and server is None:
        # Show current config
        if not ntfy_cfg:
            console.print("ntfy notifications: not configured.")
        else:
            enabled = ntfy_cfg.get("enabled", False)
            topic_status = "configured" if km.has_key(NTFY_TOPIC_ENV_VAR) else "not set"
            status_str = "enabled" if enabled else "disabled"
            console.print(f"ntfy notifications: {status_str}, topic: {topic_status}")
        return

    if action == "enable" and not km.has_key(NTFY_TOPIC_ENV_VAR):
        console.print(
            "[bold yellow]Security notice:[/bold yellow] ntfy.sh topics are PUBLIC. "
            "Anyone who knows your topic can send and receive messages."
        )
        topic = click.prompt("ntfy topic", hide_input=True)
        topic_confirm = click.prompt("Confirm ntfy topic", hide_input=True)
        if topic != topic_confirm:
            raise click.ClickException("Topics do not match. Aborting.")
        km.save_key(NTFY_TOPIC_ENV_VAR, topic)

    enabled = (
        action == "enable" if action is not None else ntfy_cfg.get("enabled", False)
    )
    ntfy_cfg["enabled"] = enabled
    ntfy_cfg.pop("topic", None)  # topics are stored in keys.env, not settings

    if server is not None:
        ntfy_cfg["server"] = server

    settings.set_notification_config("ntfy", ntfy_cfg, scope="global")
    console.print(f"ntfy notifications {'enabled' if enabled else 'disabled'}.")


# -- reset --------------------------------------------------------------------


@notify_group.command(name="reset")
@click.option("--desktop", "reset_desktop", is_flag=True, default=False)
@click.option("--ntfy", "reset_ntfy", is_flag=True, default=False)
@click.option("--all", "reset_all", is_flag=True, default=False)
def reset_cmd(reset_desktop: bool, reset_ntfy: bool, reset_all: bool) -> None:
    """Clear notification configuration."""
    settings = _get_settings()

    if reset_all:
        settings.clear_notification_config(None, scope="global")
        console.print("All notification settings cleared.")
        return

    if reset_desktop:
        settings.clear_notification_config("desktop", scope="global")
        console.print("Desktop notification settings cleared.")

    if reset_ntfy:
        settings.clear_notification_config("ntfy", scope="global")
        console.print("ntfy notification settings cleared.")

    if not reset_desktop and not reset_ntfy and not reset_all:
        raise click.UsageError("Specify at least one of: --desktop, --ntfy, --all")
