"""Register command — register a single definition file."""

from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Optional

import click

from amplifier_ipc_cli.registry import Registry


def _read_definition(fsspec: str) -> str:
    """Read a definition from a local path or HTTP(S) URL.

    Args:
        fsspec: Local file path or HTTP(S) URL pointing to a YAML definition.

    Returns:
        The YAML content as a string.

    Raises:
        FileNotFoundError: If a local path does not exist.
    """
    if fsspec.startswith("http://") or fsspec.startswith("https://"):
        with urllib.request.urlopen(fsspec, timeout=30) as response:  # noqa: S310
            return response.read().decode("utf-8")

    path = Path(fsspec)
    if not path.exists():
        raise FileNotFoundError(f"Definition file not found: {fsspec}")

    return path.read_text(encoding="utf-8")


@click.command()
@click.argument("fsspec")
@click.option(
    "--install",
    is_flag=True,
    default=False,
    help="(Placeholder) Install the registered definition.",
)
@click.option(
    "--home",
    default=None,
    help="Override $AMPLIFIER_HOME path (useful for testing).",
)
def register(fsspec: str, install: bool, home: Optional[str]) -> None:
    """Register a single definition file at FSSPEC (local path or URL).

    FSSPEC may be a local filesystem path or an HTTP(S) URL pointing to a
    YAML definition file.
    """
    # Determine source_url for HTTP sources
    is_http = fsspec.startswith("http://") or fsspec.startswith("https://")
    source_url: Optional[str] = fsspec if is_http else None

    try:
        yaml_content = _read_definition(fsspec)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    home_path = Path(home) if home else None
    registry = Registry(home=home_path)
    registry.ensure_home()

    try:
        definition_id = registry.register_definition(
            yaml_content, source_url=source_url
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Registered: {definition_id}")
