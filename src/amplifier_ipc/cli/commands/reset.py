"""Reset command — remove amplifier data directories from ~/.amplifier/."""

from __future__ import annotations

import shutil
from pathlib import Path

import click

from amplifier_ipc.cli.console import console

# -- Helpers ------------------------------------------------------------------

#: All recognised data categories (used for --preserve validation).
ALL_CATEGORIES: list[str] = ["environments", "definitions", "sessions", "keys"]


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


def _get_preserve_paths(preserve: tuple[str, ...], amp_dir: Path) -> list[Path]:
    """Return paths to remove when using --preserve (everything not in *preserve*).

    Parameters
    ----------
    preserve:
        Categories to keep.  All other categories are removed.
    amp_dir:
        Root amplifier directory.

    Returns
    -------
    list[Path]
        Paths to remove (everything outside the preserved categories).
    """
    to_remove = [cat for cat in ALL_CATEGORIES if cat not in preserve]
    paths: list[Path] = []
    for cat in to_remove:
        paths.extend(_get_target_paths(cat, amp_dir))
    return paths


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


def _print_next_steps(removed: str) -> None:
    """Print helpful post-reset guidance."""
    console.print("")
    console.print("[bold]Next steps:[/bold]")
    if removed in ("all", "definitions"):
        console.print(
            "  • Re-register agents/behaviors:  [bold]amplifier-ipc discover[/bold]"
        )
    if removed in ("all", "environments"):
        console.print(
            "  • Re-install agent environments:  "
            "[bold]amplifier-ipc install <agent>[/bold]"
        )
    if removed in ("all", "keys"):
        console.print(
            "  • Re-configure API keys:  [bold]amplifier-ipc provider configure[/bold]"
        )
    console.print(
        "  • Run init to rebuild the full setup:  [bold]amplifier-ipc init[/bold]"
    )


# -- Click command ------------------------------------------------------------


@click.command(name="reset")
@click.option(
    "--remove",
    type=click.Choice([*ALL_CATEGORIES, "all"]),
    default=None,
    help="Which data category to remove.",
)
@click.option(
    "--preserve",
    "preserve",
    multiple=True,
    type=click.Choice(ALL_CATEGORIES),
    help=(
        "Keep this category; remove everything else. "
        "Repeatable. Mutually exclusive with --remove."
    ),
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
@click.option(
    "--yes",
    "-y",
    "skip_confirm",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
def reset_cmd(
    remove: str | None,
    preserve: tuple[str, ...],
    dry_run: bool,
    home: Path | None,
    skip_confirm: bool,
) -> None:
    """Remove amplifier data from the ~/.amplifier/ directory.

    Specify WHAT to remove with one of:

    \b
      --remove <category>     Remove a specific category (or "all").
      --preserve <category>   Keep a category; remove everything else.
                              May be repeated for multiple categories to keep.

    Examples
    --------
    \b
      amplifier-ipc reset --remove sessions
      amplifier-ipc reset --remove all
      amplifier-ipc reset --preserve sessions --preserve keys
      amplifier-ipc reset --remove all --dry-run
      amplifier-ipc reset --remove definitions --yes

    Use --dry-run to preview deletions without making changes.
    Use --yes / -y to skip the confirmation prompt.
    Use --home to target a non-default amplifier directory.
    """
    amp_dir = home or Path.home() / ".amplifier"

    # --- validate option usage -----------------------------------------------
    if remove is not None and preserve:
        raise click.UsageError(
            "--remove and --preserve are mutually exclusive. Use one or the other."
        )

    if remove is None and not preserve:
        raise click.UsageError(
            "Specify what to remove with --remove <category> or "
            "--preserve <keep-category>."
        )

    # --- build target list ---------------------------------------------------
    if preserve:
        targets = _get_preserve_paths(preserve, amp_dir)
        action_desc = f"remove everything except: {', '.join(sorted(preserve))}"
    else:
        assert remove is not None  # validated above
        targets = _get_target_paths(remove, amp_dir)
        action_desc = f"remove: {remove}"

    if not targets:
        raise click.ClickException("No target paths resolved — nothing to do.")

    # --- dry-run mode --------------------------------------------------------
    if dry_run:
        console.print("[bold yellow]Dry run — nothing will be deleted.[/bold yellow]\n")
        console.print(f"Action: [bold]{action_desc}[/bold]\n")
        for path in targets:
            status = (
                "[green]exists[/green]" if path.exists() else "[dim]not found[/dim]"
            )
            console.print(f"  Would remove: {path}  ({status})")
        return

    # --- confirmation prompt -------------------------------------------------
    existing_targets = [p for p in targets if p.exists()]
    if not existing_targets:
        console.print(
            "[dim]Nothing to remove — all target paths are already absent.[/dim]"
        )
        return

    # Prompt only for broad/destructive operations (--remove all, --preserve).
    # Individual-category --remove calls proceed without confirmation to keep
    # backward compatibility with existing automation.
    needs_confirm = (remove == "all") or bool(preserve)
    if needs_confirm and not skip_confirm:
        console.print(f"\n[bold red]About to {action_desc}:[/bold red]")
        for path in existing_targets:
            console.print(f"  [red]{path}[/red]")
        click.confirm("\nProceed?", abort=True)

    # --- perform removal -----------------------------------------------------
    for path in targets:
        if path.exists():
            _remove_path(path)
            console.print(f"Removed: [red]{path}[/red]")
        else:
            console.print(f"Not found (skipped): [dim]{path}[/dim]")

    # --- post-reset guidance -------------------------------------------------
    effective_remove = remove or "all"
    _print_next_steps(effective_remove)
