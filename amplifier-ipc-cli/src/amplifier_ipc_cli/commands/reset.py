"""Reset command — remove amplifier data directories from ~/.amplifier/."""

from __future__ import annotations

import shutil
from pathlib import Path

import click

from amplifier_ipc_cli.console import console

# -- Helpers ------------------------------------------------------------------


def _get_target_paths(target: str, amp_dir: Path) -> list[Path]:
    """Return a list of paths to remove for *target* under *amp_dir*.

    Parameters
    ----------
    target:
        One of ``environments``, ``definitions``, ``sessions``, ``keys``,
        or ``all``.
    amp_dir:
        Root amplifier directory (e.g. ``~/.amplifier``).

    Returns
    -------
    list[Path]
        Paths to remove.  The paths may or may not exist on disk.
    """
    mapping: dict[str, list[Path]] = {
        "environments": [amp_dir / "environments"],
        "definitions": [
            amp_dir / "definitions",
            amp_dir / "agents.yaml",
            amp_dir / "behaviors.yaml",
        ],
        "sessions": [amp_dir / "sessions"],
        "keys": [amp_dir / "keys.env"],
    }

    if target == "all":
        paths: list[Path] = []
        for sub_paths in mapping.values():
            paths.extend(sub_paths)
        return paths

    return mapping.get(target, [])


def _remove_path(path: Path) -> None:
    """Remove *path* whether it is a file or directory tree.

    No-op if *path* does not exist.
    """
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


# -- Click command ------------------------------------------------------------


@click.command(name="reset")
@click.option(
    "--remove",
    type=click.Choice(["environments", "definitions", "sessions", "keys", "all"]),
    required=True,
    help="Which data to remove.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be removed without actually removing anything.",
)
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Amplifier home directory (default: ~/.amplifier).",
)
def reset_cmd(remove: str, dry_run: bool, home: Path | None) -> None:
    """Remove amplifier data from the ~/.amplifier/ directory.

    Use --remove to specify which category of data to wipe.
    Use --dry-run to preview what would be deleted without making changes.
    Use --home to target a non-default amplifier directory.
    """
    amp_dir = home or Path.home() / ".amplifier"
    targets = _get_target_paths(remove, amp_dir)

    if not targets:
        raise click.ClickException(f"Unknown target: {remove}")

    if dry_run:
        console.print("[bold yellow]Dry run — nothing will be deleted.[/bold yellow]\n")
        for path in targets:
            status = (
                "[green]exists[/green]" if path.exists() else "[dim]not found[/dim]"
            )
            console.print(f"  Would remove: {path}  ({status})")
        return

    for path in targets:
        if path.exists():
            _remove_path(path)
            console.print(f"Removed: [red]{path}[/red]")
        else:
            console.print(f"Not found (skipped): [dim]{path}[/dim]")
