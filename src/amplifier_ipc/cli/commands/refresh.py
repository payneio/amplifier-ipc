"""Refresh command — reinstall amplifier-ipc into all service environments.

Service subprocesses each run from their own virtualenv under
``$AMPLIFIER_HOME/environments/``.  When the host package (amplifier-ipc)
is updated locally, those venvs still have the old copy.  This command
walks every installed environment and reinstalls the protocol library so
all services pick up the latest code.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import click

from amplifier_ipc.cli.console import console


def _get_cli_source() -> tuple[str, bool]:
    """Detect the source of the currently running amplifier-ipc package.

    Returns:
        A ``(source, editable)`` tuple.

        *source* is a pip-installable string — either a local path
        (for editable / local installs) or a ``git+https://`` URL.

        *editable* is ``True`` when the CLI was installed with ``-e``
        (editable mode), meaning the installed code lives in a working
        tree and changes take effect without reinstalling.
    """
    # Detect editable install: the package source is the working tree.
    try:
        import amplifier_ipc as pkg

        pkg_init = Path(pkg.__file__).resolve()
        # Walk up from  …/src/amplifier_ipc/__init__.py  to the repo root.
        repo_root = pkg_init.parent.parent.parent
        pyproject = repo_root / "pyproject.toml"
        if pyproject.exists():
            return str(repo_root), True
    except Exception:  # noqa: BLE001
        pass

    # Fallback: non-editable install — use the package metadata.
    try:
        from importlib.metadata import distribution

        dist = distribution("amplifier-ipc")
        # direct_url.json is set by pip for VCS / local installs.
        direct = dist.read_text("direct_url.json")
        if direct:
            import json

            info = json.loads(direct)
            url: str = info.get("url", "")
            if url.startswith("file://"):
                return url.removeprefix("file://"), False
            if "vcs_info" in info:
                vcs_url = info["vcs_info"].get("vcs", "git") + "+" + url
                return vcs_url, False
    except Exception:  # noqa: BLE001
        pass

    raise click.ClickException(
        "Cannot detect the amplifier-ipc package source. "
        "Reinstall with: uv tool install -e /path/to/amplifier-ipc"
    )


@click.command("refresh")
@click.option(
    "--home",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help="Override $AMPLIFIER_HOME path.",
)
@click.option(
    "--dry-run", is_flag=True, help="Show what would be updated without making changes."
)
def refresh(home: str | None, dry_run: bool) -> None:
    """Reinstall amplifier-ipc into all service environments.

    Ensures every service subprocess runs the same version of the
    protocol library as the CLI host.  Run this after making local
    changes to amplifier-ipc source code.
    """
    amp_home = Path(home) if home else Path.home() / ".amplifier"
    envs_dir = amp_home / "environments"

    if not envs_dir.exists():
        console.print(
            "[dim]No environments directory found — nothing to refresh.[/dim]"
        )
        return

    source, editable = _get_cli_source()
    env_dirs = sorted(
        d for d in envs_dir.iterdir() if d.is_dir() and (d / "bin" / "python3").exists()
    )

    if not env_dirs:
        console.print("[dim]No installed environments found.[/dim]")
        return

    console.print(
        f"Source: [bold]{source}[/bold] ({'editable' if editable else 'pinned'})"
    )
    console.print(f"Environments: [bold]{len(env_dirs)}[/bold]\n")

    for env_path in env_dirs:
        name = env_path.name
        python = str(env_path / "bin" / "python3")
        short = name[:40] + "..." if len(name) > 43 else name

        if dry_run:
            console.print(f"  [dim]would update[/dim] {short}")
            continue

        args = ["uv", "pip", "install", "--python", python]
        if editable:
            args.append("-e")
        args.append(source)

        try:
            subprocess.run(args, check=True, capture_output=True, text=True)  # noqa: S603
            console.print(f"  [green]\u2713[/green] {short}")
        except subprocess.CalledProcessError as exc:
            console.print(f"  [red]\u2717[/red] {short}: {exc.stderr.strip()[:120]}")

    if dry_run:
        console.print(
            f"\n[dim]Dry run complete — {len(env_dirs)} environments would be updated.[/dim]"
        )
    else:
        console.print(f"\n[green]Refreshed {len(env_dirs)} environments.[/green]")
