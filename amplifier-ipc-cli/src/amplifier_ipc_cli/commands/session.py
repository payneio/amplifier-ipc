"""Session management commands for amplifier-ipc-cli.

Provides CLI subcommands for listing, viewing, deleting, and cleaning up
amplifier session directories from the persistence layer.
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.panel import Panel
from rich.table import Table

from amplifier_ipc_cli.console import console


# -- Helper functions ---------------------------------------------------------


def _get_default_sessions_dir() -> Path:
    """Return the default sessions directory (~/.amplifier/sessions)."""
    return Path("~/.amplifier/sessions").expanduser()


def _format_time_ago(dt: datetime) -> str:
    """Return a human-readable 'time ago' string for the given datetime."""
    now = datetime.now(tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    seconds = int(diff.total_seconds())

    if seconds < 60:
        return f"{seconds}s ago"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m ago"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    elif seconds < 86400 * 30:
        days = seconds // 86400
        return f"{days}d ago"
    elif seconds < 86400 * 365:
        months = seconds // (86400 * 30)
        return f"{months}mo ago"
    else:
        years = seconds // (86400 * 365)
        return f"{years}y ago"


def _parse_transcript(session_dir: Path) -> tuple[int, int]:
    """Parse transcript.jsonl and return (total_messages, user_turns)."""
    transcript_file = session_dir / "transcript.jsonl"
    if not transcript_file.exists():
        return 0, 0

    total = 0
    user_turns = 0
    try:
        for line in transcript_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                total += 1
                if msg.get("role") == "user":
                    user_turns += 1
            except json.JSONDecodeError:
                continue
    except OSError:
        return 0, 0

    return total, user_turns


def _load_metadata(session_dir: Path) -> dict:
    """Load and return metadata.json from a session directory."""
    metadata_file = session_dir / "metadata.json"
    if not metadata_file.exists():
        return {}
    try:
        return json.loads(metadata_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _find_session(sessions_dir: Path, prefix: str) -> str | None:
    """Find a session directory by ID prefix; exact match wins for ambiguity."""
    if not sessions_dir.exists():
        return None

    sessions = [d.name for d in sessions_dir.iterdir() if d.is_dir()]

    # Exact match wins
    if prefix in sessions:
        return prefix

    # Prefix match
    matches = [s for s in sessions if s.startswith(prefix)]
    if len(matches) == 1:
        return matches[0]

    return None


# -- Session group ------------------------------------------------------------


@click.group(name="session", invoke_without_command=True)
@click.option(
    "--sessions-dir",
    default=None,
    help="Override sessions directory (default: ~/.amplifier/sessions).",
)
@click.pass_context
def session_group(ctx: click.Context, sessions_dir: str | None) -> None:
    """Manage amplifier sessions."""
    ctx.ensure_object(dict)
    if sessions_dir is not None:
        ctx.obj["sessions_dir"] = Path(sessions_dir)
    else:
        ctx.obj["sessions_dir"] = _get_default_sessions_dir()

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# -- list ---------------------------------------------------------------------


@session_group.command(name="list")
@click.option(
    "--limit",
    "-n",
    default=20,
    show_default=True,
    help="Maximum number of sessions to show.",
)
@click.pass_context
def list_sessions(ctx: click.Context, limit: int) -> None:
    """List sessions sorted by modification time (newest first)."""
    sessions_dir: Path = ctx.obj["sessions_dir"]

    if not sessions_dir.exists():
        console.print("No sessions found.")
        return

    session_dirs = sorted(
        [d for d in sessions_dir.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )[:limit]

    if not session_dirs:
        console.print("No sessions found.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="green")
    table.add_column("Session ID", style="cyan")
    table.add_column("Msgs", style="yellow", justify="right")
    table.add_column("Modified", style="dim")

    for session_dir in session_dirs:
        metadata = _load_metadata(session_dir)
        name = metadata.get("name", session_dir.name)
        session_id = session_dir.name
        truncated_id = session_id[:8] + "..." if len(session_id) > 8 else session_id
        total_msgs, _ = _parse_transcript(session_dir)
        mtime = datetime.fromtimestamp(session_dir.stat().st_mtime, tz=timezone.utc)
        time_ago = _format_time_ago(mtime)
        table.add_row(name, truncated_id, str(total_msgs), time_ago)

    console.print(table)


# -- show ---------------------------------------------------------------------


@session_group.command(name="show")
@click.argument("session_id")
@click.pass_context
def show_session(ctx: click.Context, session_id: str) -> None:
    """Show details for a session identified by SESSION_ID (or prefix)."""
    sessions_dir: Path = ctx.obj["sessions_dir"]

    matched = _find_session(sessions_dir, session_id)
    if matched is None:
        raise click.ClickException(f"Session not found: {session_id}")

    session_dir = sessions_dir / matched
    metadata = _load_metadata(session_dir)
    total_msgs, user_turns = _parse_transcript(session_dir)

    content = "\n".join(
        [
            f"Session ID: {matched}",
            f"Name: {metadata.get('name', 'Unknown')}",
            f"Status: {metadata.get('status', 'unknown')}",
            f"Messages: {total_msgs}",
            f"User Turns: {user_turns}",
        ]
    )

    panel = Panel(content, title="Session Details", border_style="blue")
    console.print(panel)


# -- delete -------------------------------------------------------------------


@session_group.command(name="delete")
@click.argument("session_id")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt.",
)
@click.pass_context
def delete_session(ctx: click.Context, session_id: str, force: bool) -> None:
    """Delete a session directory identified by SESSION_ID (or prefix)."""
    sessions_dir: Path = ctx.obj["sessions_dir"]

    matched = _find_session(sessions_dir, session_id)
    if matched is None:
        raise click.ClickException(f"Session not found: {session_id}")

    session_dir = sessions_dir / matched

    if not force:
        click.confirm(f"Delete session {matched}?", abort=True)

    shutil.rmtree(session_dir)
    console.print(f"Deleted session [cyan]{matched}[/cyan].")


# -- cleanup ------------------------------------------------------------------


@session_group.command(name="cleanup")
@click.option(
    "--days",
    "-d",
    default=30,
    show_default=True,
    help="Remove sessions with mtime older than N days.",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt.",
)
@click.pass_context
def cleanup_sessions(ctx: click.Context, days: int, force: bool) -> None:
    """Remove session directories with mtime older than N days."""
    sessions_dir: Path = ctx.obj["sessions_dir"]

    if not sessions_dir.exists():
        console.print("No sessions directory found.")
        return

    cutoff = time.time() - (days * 86400)
    old_sessions = [
        d for d in sessions_dir.iterdir() if d.is_dir() and d.stat().st_mtime < cutoff
    ]

    if not old_sessions:
        console.print(f"No sessions older than {days} days.")
        return

    if not force:
        click.confirm(
            f"Delete {len(old_sessions)} session(s) older than {days} days?",
            abort=True,
        )

    removed = 0
    for session_dir in old_sessions:
        shutil.rmtree(session_dir)
        removed += 1

    console.print(f"Removed [yellow]{removed}[/yellow] session(s).")
