"""Discover command — scans a location for agent/behavior YAML definitions."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag

import click
import yaml
from rich.console import Console

from amplifier_ipc_cli.registry import Registry

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_parse_definition(yaml_path: Path, results: list[dict[str, Any]]) -> None:
    """Parse a YAML file and append to results if it is an agent or behavior definition.

    Args:
        yaml_path: Path to the YAML file to parse.
        results: List to append matching definitions to.
    """
    try:
        raw_content = yaml_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw_content)
    except Exception:
        return

    if not isinstance(parsed, dict):
        return

    def_type = parsed.get("type")
    if def_type not in ("agent", "behavior"):
        return

    local_ref = parsed.get("local_ref", "")
    results.append(
        {
            "type": def_type,
            "local_ref": local_ref,
            "path": str(yaml_path.resolve()),
            "raw_content": raw_content,
        }
    )


def _clone_git_location(location: str, tmp_dir: str) -> str:
    """Clone a git URL into an existing directory and return the path to scan.

    Supports ``#subdirectory=<subdir>`` fragment to point to a subdirectory
    within the cloned repository.

    The caller is responsible for creating *and* cleaning up ``tmp_dir``
    (e.g. via ``tempfile.TemporaryDirectory`` as a context manager).

    Args:
        location: git URL, possibly with a ``#subdirectory=`` fragment.
        tmp_dir: Pre-created temporary directory to clone into.

    Returns:
        Absolute path to the (sub)directory to scan.
    """
    # Strip leading git+ prefix if present
    url = location
    if url.startswith("git+"):
        url = url[4:]

    # Extract optional subdirectory fragment: #subdirectory=subdir
    url, fragment = urldefrag(url)
    subdir: str | None = None
    if fragment.startswith("subdirectory="):
        subdir = fragment[len("subdirectory=") :]

    subprocess.run(
        ["git", "clone", "--depth", "1", url, tmp_dir],
        check=True,
        capture_output=True,
    )

    if subdir:
        return str(Path(tmp_dir) / subdir)
    return tmp_dir


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_location(location: str) -> list[dict[str, Any]]:
    """Recursively scan a filesystem path for agent and behavior YAML definitions.

    Walks ``location`` recursively and inspects every ``.yaml`` / ``.yml``
    file.  Files whose parsed content contains a ``type`` key equal to
    ``"agent"`` or ``"behavior"`` are included in the result.

    Args:
        location: Absolute or relative path to a directory to scan.

    Returns:
        List of dicts, each containing at minimum:
        - ``type``: ``"agent"`` or ``"behavior"``
        - ``local_ref``: value of the ``local_ref`` field (may be empty string)
        - ``path``: absolute path to the YAML file
        - ``raw_content``: raw text content of the YAML file
    """
    results: list[dict[str, Any]] = []
    root = Path(location)

    for yaml_path in sorted(root.rglob("*.yaml")):
        _try_parse_definition(yaml_path, results)

    for yaml_path in sorted(root.rglob("*.yml")):
        _try_parse_definition(yaml_path, results)

    return results


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------


@click.command()
@click.argument("location")
@click.option(
    "--register",
    is_flag=True,
    default=False,
    help="Register found definitions to the local registry.",
)
@click.option(
    "--install",
    is_flag=True,
    default=False,
    help="(Placeholder) Install found definitions.",
)
@click.option(
    "--home",
    default=None,
    help="Override $AMPLIFIER_HOME path (useful for testing).",
)
def discover(location: str, register: bool, install: bool, home: str | None) -> None:
    """Scan LOCATION for agent/behavior YAML definitions.

    LOCATION may be a local filesystem path or a git URL
    (prefixed with ``git+`` or an https://github.com… URL).
    """
    # Resolve location: handle git URLs
    is_git = location.startswith("git+") or (
        location.startswith("https://") and "github" in location
    )
    if is_git:
        console.print(f"[bold]Cloning[/bold] {location} …")
        try:
            with tempfile.TemporaryDirectory(prefix="amplifier_discover_") as tmp_dir:
                scan_path = _clone_git_location(location, tmp_dir)
                console.print(f"[bold]Scanning[/bold] {scan_path} …")
                definitions = scan_location(scan_path)
        except subprocess.CalledProcessError as exc:
            console.print(f"[red]Failed to clone repository:[/red] {exc}")
            raise click.Abort() from exc
    else:
        scan_path = location
        console.print(f"[bold]Scanning[/bold] {scan_path} …")
        definitions = scan_location(scan_path)

    count = len(definitions)
    if count == 0:
        console.print("[yellow]No definitions found.[/yellow]")
    else:
        console.print(f"[green]Found {count} definition(s):[/green]")
        for item in definitions:
            console.print(
                f"  [{item['type']}] {item['local_ref'] or '(no local_ref)'}"
                f"  {item['path']}"
            )

    if register and definitions:
        home_path = Path(home) if home else None
        registry = Registry(home=home_path)
        registry.ensure_home()
        for item in definitions:
            registry.register_definition(item["raw_content"])
            console.print(
                f"[blue]Registered[/blue] {item['type']} '{item['local_ref']}'"
            )
