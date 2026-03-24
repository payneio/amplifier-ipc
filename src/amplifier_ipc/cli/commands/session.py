"""Session management commands for amplifier-ipc-cli.

Provides CLI subcommands for listing, viewing, deleting, forking, resuming,
and cleaning up amplifier session directories from the persistence layer.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import click
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from amplifier_ipc.cli.console import console


# -- Helper functions ---------------------------------------------------------


def _get_default_sessions_dir() -> Path:
    """Return the default sessions directory (~/.amplifier/sessions)."""
    return Path("~/.amplifier/sessions").expanduser()


def _get_projects_base_dir() -> Path:
    """Return the base projects directory (~/.amplifier/projects/)."""
    return Path("~/.amplifier/projects").expanduser()


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


def _find_session_any_project(prefix: str) -> tuple[str, Path] | None:
    """Search all project directories for a session matching *prefix*.

    Returns ``(session_id, sessions_dir)`` for the first match found, or
    ``None`` if no match exists across any project.
    """
    projects_base = _get_projects_base_dir()
    if not projects_base.exists():
        return None

    for project_dir in sorted(projects_base.iterdir()):
        if not project_dir.is_dir():
            continue
        sessions_dir = project_dir / "sessions"
        matched = _find_session(sessions_dir, prefix)
        if matched is not None:
            return matched, sessions_dir

    return None


def _collect_all_sessions() -> list[tuple[str, Path, str]]:
    """Collect all sessions across all projects and the default sessions dir.

    Returns a list of ``(session_id, sessions_dir, project_name)`` tuples.
    """
    result: list[tuple[str, Path, str]] = []

    # Include the default sessions directory (~/.amplifier/sessions/)
    default_dir = _get_default_sessions_dir()
    if default_dir.exists():
        for sdir in default_dir.iterdir():
            if sdir.is_dir():
                result.append((sdir.name, default_dir, "default"))

    # Include project-scoped session directories (~/.amplifier/projects/*/sessions/)
    projects_base = _get_projects_base_dir()
    if projects_base.exists():
        for project_dir in sorted(projects_base.iterdir()):
            if not project_dir.is_dir():
                continue
            sessions_dir = project_dir / "sessions"
            if not sessions_dir.exists():
                continue
            project_name = project_dir.name
            for sdir in sessions_dir.iterdir():
                if sdir.is_dir():
                    result.append((sdir.name, sessions_dir, project_name))

    return result


def _fork_session(
    sessions_dir: Path, source_id: str, *, turn: int | None = None
) -> tuple[str, int]:
    """Snapshot a session transcript and create a new forked session.

    Parameters
    ----------
    sessions_dir:
        Root sessions directory.
    source_id:
        The exact session ID to fork.
    turn:
        1-indexed user turn at which to truncate.  When specified, the
        transcript is cut after the assistant response that follows the
        *turn*-th user message.  When ``None`` the full transcript is copied.

    Returns
    -------
    tuple[str, int]
        ``(new_session_id, message_count)``
    """
    source_dir = sessions_dir / source_id

    # --- read messages -------------------------------------------------------
    transcript_file = source_dir / "transcript.jsonl"
    messages: list[dict] = []
    if transcript_file.exists():
        for line in transcript_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # --- truncate at turn ----------------------------------------------------
    if turn is not None:
        kept: list[dict] = []
        user_turns_seen = 0
        for i, msg in enumerate(messages):
            kept.append(msg)
            if msg.get("role") == "user":
                user_turns_seen += 1
                if user_turns_seen >= turn:
                    # include the next assistant response if present
                    if (
                        i + 1 < len(messages)
                        and messages[i + 1].get("role") == "assistant"
                    ):
                        kept.append(messages[i + 1])
                    break
        messages = kept

    # --- create new session directory ----------------------------------------
    new_id = f"fork_{uuid4().hex[:12]}"
    new_dir = sessions_dir / new_id
    new_dir.mkdir(parents=True, exist_ok=True)

    # --- write transcript.jsonl with compact separators ----------------------
    lines = [json.dumps(m, separators=(",", ":")) for m in messages]
    (new_dir / "transcript.jsonl").write_text("\n".join(lines))

    # --- copy and update metadata --------------------------------------------
    source_metadata = _load_metadata(source_dir)
    new_metadata = dict(source_metadata)
    new_metadata["session_id"] = new_id
    original_name = source_metadata.get("name", source_id)
    new_metadata["name"] = f"{original_name} (fork)"
    new_metadata["forked_from"] = source_id
    new_metadata["status"] = "active"
    if turn is not None:
        new_metadata["forked_at_turn"] = turn
    (new_dir / "metadata.json").write_text(json.dumps(new_metadata))

    return new_id, len(messages)


def _build_lineage_tree(sessions_dir: Path, session_id: str) -> Tree:
    """Build and return a Rich Tree showing the lineage of *session_id*.

    Walks up the ``forked_from`` chain to find the root session, then scans
    all siblings to show children at each level.
    """
    # Collect all session metadata in this sessions directory
    all_meta: dict[str, dict] = {}
    if sessions_dir.exists():
        for d in sessions_dir.iterdir():
            if d.is_dir():
                all_meta[d.name] = _load_metadata(d)

    # Build children index: parent_id → list of child_ids
    children: dict[str, list[str]] = {}
    for sid, meta in all_meta.items():
        parent = meta.get("forked_from") or meta.get("parent_id")
        if parent:
            children.setdefault(parent, []).append(sid)

    # Walk up to the root
    root_id = session_id
    visited: set[str] = set()
    while True:
        meta = all_meta.get(root_id, {})
        parent = meta.get("forked_from") or meta.get("parent_id")
        if not parent or parent == root_id or parent in visited:
            break
        visited.add(root_id)
        root_id = parent

    def _label(sid: str) -> str:
        meta = all_meta.get(sid, {})
        name = meta.get("name", sid)
        parts = [f"[cyan]{sid[:12]}[/cyan]"]
        if name and name != sid:
            parts.append(f"[green]{name}[/green]")
        if sid == session_id:
            parts.append("[bold yellow]← current[/bold yellow]")
        forked_at = meta.get("forked_at_turn")
        if forked_at is not None:
            parts.append(f"[dim](turn {forked_at})[/dim]")
        return "  ".join(parts)

    root_node = Tree(_label(root_id))

    def _add_children(node: Tree, parent_id: str, depth: int = 0) -> None:
        if depth > 20:  # guard against cycles
            return
        for child_id in sorted(children.get(parent_id, [])):
            child_node = node.add(_label(child_id))
            _add_children(child_node, child_id, depth + 1)

    _add_children(root_node, root_id)
    return root_node


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
@click.option(
    "--all-projects",
    "all_projects",
    is_flag=True,
    default=False,
    help="Scan all projects under ~/.amplifier/projects/ (not just current project).",
)
@click.option(
    "--tree",
    "tree_session",
    default=None,
    metavar="SESSION_ID",
    help="Display lineage tree for the given session ID (or prefix).",
)
@click.pass_context
def list_sessions(
    ctx: click.Context, limit: int, all_projects: bool, tree_session: str | None
) -> None:
    """List sessions sorted by modification time (newest first).

    Use --all-projects to show sessions from every project directory.
    Use --tree SESSION_ID to display the fork/parent lineage of a session.
    """
    sessions_dir: Path = ctx.obj["sessions_dir"]

    # ---- tree mode ----------------------------------------------------------
    if tree_session is not None:
        # Try to resolve in current sessions_dir first, then all projects
        matched = _find_session(sessions_dir, tree_session)
        resolved_sessions_dir = sessions_dir
        if matched is None and all_projects:
            result = _find_session_any_project(tree_session)
            if result is not None:
                matched, resolved_sessions_dir = result
        if matched is None:
            raise click.ClickException(f"Session not found: {tree_session}")
        tree = _build_lineage_tree(resolved_sessions_dir, matched)
        console.print("\n[bold]Session Lineage Tree[/bold]\n")
        console.print(tree)
        return

    # ---- all-projects mode --------------------------------------------------
    if all_projects:
        all_items = _collect_all_sessions()
        if not all_items:
            console.print("No sessions found across any project.")
            return

        # Sort by mtime descending
        def _mtime(item: tuple[str, Path, str]) -> float:
            sid, sdir, _ = item
            try:
                return (sdir / sid).stat().st_mtime
            except OSError:
                return 0.0

        all_items.sort(key=_mtime, reverse=True)
        all_items = all_items[:limit]

        table = Table(show_header=True, header_style="bold")
        table.add_column("Project", style="magenta")
        table.add_column("Name", style="green")
        table.add_column("Session ID", style="cyan")
        table.add_column("Msgs", style="yellow", justify="right")
        table.add_column("Modified", style="dim")

        for session_id, sdir, project_name in all_items:
            session_path = sdir / session_id
            metadata = _load_metadata(session_path)
            name = metadata.get("name", session_id)
            truncated_id = session_id[:8] + "..." if len(session_id) > 8 else session_id
            total_msgs, _ = _parse_transcript(session_path)
            try:
                mtime = datetime.fromtimestamp(
                    session_path.stat().st_mtime, tz=timezone.utc
                )
                time_ago = _format_time_ago(mtime)
            except OSError:
                time_ago = "unknown"
            table.add_row(project_name, name, truncated_id, str(total_msgs), time_ago)

        console.print(table)
        return

    # ---- default mode (current project) ------------------------------------
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


# -- fork ---------------------------------------------------------------------


@session_group.command(name="fork")
@click.argument("session_id")
@click.option(
    "--at-turn",
    "-t",
    "at_turn",
    default=None,
    type=int,
    help="Fork at this user turn (1-indexed). Omit to copy the full transcript.",
)
@click.option(
    "--name",
    "-n",
    "fork_name",
    default=None,
    help="Name for the forked session.",
)
@click.option(
    "--resume",
    "-r",
    "auto_resume",
    is_flag=True,
    default=False,
    help="After forking, print the command to resume the new session.",
)
@click.pass_context
def session_fork(
    ctx: click.Context,
    session_id: str,
    at_turn: int | None,
    fork_name: str | None,
    auto_resume: bool,
) -> None:
    """Fork SESSION_ID into a new session, optionally truncating at a turn.

    Use --name to give the fork a custom name.
    Use --resume to print the resume command immediately after forking.
    """
    sessions_dir: Path = ctx.obj["sessions_dir"]

    matched = _find_session(sessions_dir, session_id)
    if matched is None:
        raise click.ClickException(f"Session not found: {session_id}")

    new_id, msg_count = _fork_session(sessions_dir, matched, turn=at_turn)

    # Apply custom name if provided
    if fork_name is not None:
        new_dir = sessions_dir / new_id
        metadata = _load_metadata(new_dir)
        metadata["name"] = fork_name
        (new_dir / "metadata.json").write_text(json.dumps(metadata))

    display_name = (
        fork_name
        or f"{_load_metadata(sessions_dir / matched).get('name', matched)} (fork)"
    )

    console.print(f"Forked [cyan]{matched}[/cyan] → [green]{new_id}[/green]")
    if fork_name:
        console.print(f"Name: [bold]{display_name}[/bold]")
    console.print(f"Messages copied: [yellow]{msg_count}[/yellow]")
    if at_turn is not None:
        console.print(f"Truncated at user turn [yellow]{at_turn}[/yellow]")

    resume_cmd = f"amplifier-ipc session resume {new_id}"
    if auto_resume:
        console.print(f"\nResume with:\n  [bold cyan]{resume_cmd}[/bold cyan]")
    else:
        console.print(f"Resume with: [bold]{resume_cmd}[/bold]")


# -- resume -------------------------------------------------------------------


@session_group.command(name="resume")
@click.argument("session_id", required=False, default=None)
@click.pass_context
def resume_session(
    ctx: click.Context,
    session_id: str | None,
) -> None:
    """Resume a session by printing the run command for it.

    If SESSION_ID is omitted, shows a paginated list of recent sessions and
    lets you pick one interactively.

    After selection, prints the ``amplifier-ipc run`` command to use.
    """
    sessions_dir: Path = ctx.obj["sessions_dir"]

    # -- Direct invocation with a session ID ----------------------------------
    if session_id is not None:
        matched = _find_session(sessions_dir, session_id)
        if matched is None:
            raise click.ClickException(f"Session not found: {session_id}")
        _print_resume_command(sessions_dir, matched)
        return

    # -- Interactive paginated picker -----------------------------------------
    if not sessions_dir.exists():
        console.print("No sessions found.")
        return

    all_dirs = sorted(
        [d for d in sessions_dir.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )

    if not all_dirs:
        console.print("No sessions found.")
        return

    page_size = 10
    total = len(all_dirs)
    page = 0

    while True:
        start = page * page_size
        end = min(start + page_size, total)
        page_dirs = all_dirs[start:end]
        total_pages = (total + page_size - 1) // page_size

        console.print(
            f"\n[bold]Sessions[/bold] (page {page + 1}/{total_pages}, {total} total)\n"
        )

        for i, sdir in enumerate(page_dirs, start=start + 1):
            meta = _load_metadata(sdir)
            name = meta.get("name", sdir.name)
            sid_short = sdir.name[:8] + "..."
            total_msgs, _ = _parse_transcript(sdir)
            try:
                mtime = datetime.fromtimestamp(sdir.stat().st_mtime, tz=timezone.utc)
                ago = _format_time_ago(mtime)
            except OSError:
                ago = "unknown"
            console.print(
                f"  [dim]{i:>3}.[/dim] [green]{name}[/green]"
                f" [cyan]({sid_short})[/cyan]"
                f" [yellow]{total_msgs} msgs[/yellow]"
                f" [dim]{ago}[/dim]"
            )

        hints: list[str] = ["number to select", "q to quit"]
        if page > 0:
            hints.append("p for prev")
        if end < total:
            hints.append("n for next")
        console.print(f"\n[dim]  {' · '.join(hints)}[/dim]")

        try:
            raw = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Cancelled.[/dim]")
            sys.exit(0)

        if raw == "q":
            console.print("[dim]Cancelled.[/dim]")
            return
        elif raw == "n":
            if end < total:
                page += 1
            else:
                console.print("[dim]Already on last page.[/dim]")
        elif raw == "p":
            if page > 0:
                page -= 1
            else:
                console.print("[dim]Already on first page.[/dim]")
        else:
            try:
                choice = int(raw)
            except ValueError:
                console.print("[red]Invalid input. Enter a number or n/p/q.[/red]")
                continue

            if 1 <= choice <= total:
                chosen_dir = all_dirs[choice - 1]
                _print_resume_command(sessions_dir, chosen_dir.name)
                return
            else:
                console.print(
                    f"[red]Please enter a number between 1 and {total}.[/red]"
                )


def _print_resume_command(
    sessions_dir: Path,
    session_id: str,
) -> None:
    """Print the amplifier-ipc run command to resume *session_id*."""
    meta = _load_metadata(sessions_dir / session_id)
    agent = meta.get("agent", "<agent>")
    parts = ["amplifier-ipc", "run", "-a", agent, "-s", session_id]
    cmd = " ".join(parts)
    console.print(f"\nResume command:\n  [bold cyan]{cmd}[/bold cyan]\n")
