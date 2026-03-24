"""Version command — displays CLI and host package versions."""

from __future__ import annotations

import importlib.metadata
import os
import platform
import sys
from pathlib import Path

import click
import yaml
from rich.table import Table

from amplifier_ipc.cli import __version__
from amplifier_ipc.cli.console import console

# Marker used to detect existing completion entries (idempotency guard).
_COMPLETION_MARKER = "# amplifier-ipc shell completion"


def _get_host_version() -> str:
    """Return the installed amplifier-ipc-host package version, or 'unknown' on failure."""
    try:
        return importlib.metadata.version("amplifier-ipc-host")
    except Exception:  # noqa: BLE001
        return "unknown"


def _get_amplifier_home() -> Path:
    """Return the AMPLIFIER_HOME directory (env var or ~/.amplifier)."""
    env_home = os.environ.get("AMPLIFIER_HOME")
    if env_home:
        return Path(env_home)
    return Path.home() / ".amplifier"


def _count_registered(yaml_path: Path) -> int:
    """Return the number of entries in an alias YAML file (agents/behaviors)."""
    if not yaml_path.exists():
        return 0
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return len(data)
        return 0
    except Exception:  # noqa: BLE001
        return 0


def install_completion(shell: str | None = None) -> None:
    """Install shell tab-completion for amplifier-ipc.

    Detects the current shell from ``$SHELL`` when *shell* is not provided.
    Idempotent: checks for an existing marker before writing.

    Supported shells
    ----------------
    * bash  — appends eval line to ``~/.bashrc``
    * zsh   — appends eval line to ``~/.zshrc``
    * fish  — writes completion file to
              ``~/.config/fish/completions/amplifier-ipc.fish``
    """
    if shell is None:
        shell_env = os.environ.get("SHELL", "")
        shell_name = Path(shell_env).name if shell_env else ""
        if shell_name in ("bash", "zsh", "fish"):
            shell = shell_name
        else:
            raise click.ClickException(
                f"Could not detect shell from $SHELL={shell_env!r}. "
                "Pass --install-completion=<bash|zsh|fish> explicitly."
            )

    if shell == "bash":
        rc_path = Path.home() / ".bashrc"
        eval_line = 'eval "$(_AMPLIFIER_IPC_COMPLETE=bash_source amplifier-ipc)"'
        _append_completion_line(rc_path, eval_line)
        console.print(
            f"[green]✓[/green] bash completion installed in [dim]{rc_path}[/dim]"
        )
        console.print("  Reload your shell or run: [bold]source ~/.bashrc[/bold]")

    elif shell == "zsh":
        rc_path = Path.home() / ".zshrc"
        eval_line = 'eval "$(_AMPLIFIER_IPC_COMPLETE=zsh_source amplifier-ipc)"'
        _append_completion_line(rc_path, eval_line)
        console.print(
            f"[green]✓[/green] zsh completion installed in [dim]{rc_path}[/dim]"
        )
        console.print("  Reload your shell or run: [bold]source ~/.zshrc[/bold]")

    elif shell == "fish":
        fish_dir = Path.home() / ".config" / "fish" / "completions"
        fish_dir.mkdir(parents=True, exist_ok=True)
        fish_file = fish_dir / "amplifier-ipc.fish"
        completion_script = (
            f"{_COMPLETION_MARKER}\n"
            "set -x _AMPLIFIER_IPC_COMPLETE fish_source\n"
            "amplifier-ipc | source\n"
        )
        if fish_file.exists() and _COMPLETION_MARKER in fish_file.read_text():
            console.print(
                f"[dim]fish completion already installed at {fish_file}[/dim]"
            )
            return
        fish_file.write_text(completion_script, encoding="utf-8")
        console.print(
            f"[green]✓[/green] fish completion installed at [dim]{fish_file}[/dim]"
        )

    else:
        raise click.ClickException(
            f"Unsupported shell: {shell!r}. Supported: bash, zsh, fish."
        )


def _append_completion_line(rc_path: Path, eval_line: str) -> None:
    """Append *eval_line* to *rc_path* if not already present (idempotent)."""
    existing = rc_path.read_text(encoding="utf-8") if rc_path.exists() else ""
    if _COMPLETION_MARKER in existing or eval_line in existing:
        console.print(f"[dim]Completion already configured in {rc_path}[/dim]")
        return
    block = f"\n{_COMPLETION_MARKER}\n{eval_line}\n"
    with rc_path.open("a", encoding="utf-8") as fh:
        fh.write(block)


@click.command()
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Show detailed environment and registry information.",
)
@click.option(
    "--install-completion",
    "completion_shell",
    default=None,
    metavar="SHELL",
    help="Install tab completion for SHELL (bash, zsh, or fish).",
)
def version(verbose: bool, completion_shell: str | None) -> None:
    """Display the CLI and amplifier-ipc-host versions.

    Use --verbose for a full environment report including Python version,
    platform, install paths, and registered agent/behavior counts.

    Use --install-completion=<shell> to set up shell tab completion.
    """
    if completion_shell is not None:
        install_completion(completion_shell)
        return

    host_ver = _get_host_version()

    if not verbose:
        console.print(
            f"amplifier-ipc-cli {__version__} (amplifier-ipc-host {host_ver})"
        )
        return

    # -- Verbose rich table ---------------------------------------------------
    amp_home = _get_amplifier_home()
    agent_count = _count_registered(amp_home / "agents.yaml")
    behavior_count = _count_registered(amp_home / "behaviors.yaml")

    # Install path — the directory containing this module
    install_path = Path(__file__).parent.parent.parent

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="dim", no_wrap=True)
    table.add_column("Value")

    rows = [
        ("CLI version", f"[bold]{__version__}[/bold]"),
        ("Host version", host_ver),
        ("Python version", sys.version.split()[0]),
        ("Platform", platform.platform()),
        ("Install path", str(install_path)),
        ("AMPLIFIER_HOME", str(amp_home)),
        ("Registered agents", str(agent_count)),
        ("Registered behaviors", str(behavior_count)),
    ]

    for key, value in rows:
        table.add_row(key, value)

    console.print("\n[bold]amplifier-ipc environment[/bold]\n")
    console.print(table)
    console.print("")
