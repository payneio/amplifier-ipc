"""Interactive REPL for agent sessions."""

from __future__ import annotations

import asyncio
import json
import re
import signal
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from amplifier_ipc.host.events import (
    ApprovalRequestEvent,
    ChildSessionEndEvent,
    ChildSessionEvent,
    ChildSessionStartEvent,
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
    TodoUpdateEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from amplifier_ipc.host.host import Host

from amplifier_ipc.cli.approval_provider import CLIApprovalHandler
from amplifier_ipc.cli.ui.message_renderer import render_message


# ---------------------------------------------------------------------------
# @mention processing
# ---------------------------------------------------------------------------

_MENTION_RE = re.compile(r"@([\w./~-]+)")


def _process_mentions(user_input: str, console: Console) -> str:
    """Expand ``@path/to/file`` mentions in *user_input*.

    For each unique ``@path`` found, reads the file and prepends it as a
    ``<context_file>`` block before the user message.  Unreadable paths are
    skipped with a printed warning.  The same file is included only once even
    if mentioned multiple times.

    Args:
        user_input: Raw user input that may contain ``@path`` mentions.
        console:    Rich console used to print warnings.

    Returns:
        Expanded string with ``<context_file>`` blocks prepended, or the
        original string if no valid ``@path`` mentions were found.
    """
    seen: dict[str, str] = {}  # resolved_path -> content (insertion-ordered)

    for match in _MENTION_RE.finditer(user_input):
        raw_path = match.group(1)
        resolved = Path(raw_path).expanduser()
        if not resolved.is_absolute():
            resolved = Path.cwd() / resolved
        key = str(resolved)
        if key in seen:
            continue
        try:
            file_size = resolved.stat().st_size
            if file_size > 512 * 1024:
                console.print(
                    f"[yellow]Warning: @{raw_path} is too large to include "
                    f"({file_size} bytes > 512 KB limit)[/yellow]"
                )
                continue
            seen[key] = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            console.print(f"[yellow]Warning: could not read @{raw_path}[/yellow]")

    if not seen:
        return user_input

    # Strip @mentions from the message so prose reads cleanly after the blocks
    stripped_msg = _MENTION_RE.sub("", user_input).strip()

    parts = [
        f'<context_file paths="{path}">\n{content}\n</context_file>'
        for path, content in seen.items()
    ]
    return "\n\n".join(parts) + "\n\n" + stripped_msg


# ---------------------------------------------------------------------------
# Cancellation state
# ---------------------------------------------------------------------------


class CancellationState:
    """Cooperative cancellation state for the REPL execution loop.

    All state mutations are synchronous so they are safe to call directly
    from a SIGINT handler without race conditions on rapid double Ctrl+C.
    """

    def __init__(self) -> None:
        self.is_cancelled: bool = False
        self.is_immediate: bool = False
        self.current_tool: str | None = None

    def request_graceful(self) -> None:
        """First Ctrl+C — mark as gracefully cancelled."""
        self.is_cancelled = True

    def request_immediate(self) -> None:
        """Second Ctrl+C — mark for immediate cancellation."""
        self.is_immediate = True

    def reset(self) -> None:
        """Reset all state for a new execution cycle."""
        self.is_cancelled = False
        self.is_immediate = False
        self.current_tool = None


# ---------------------------------------------------------------------------
# Event helpers
# ---------------------------------------------------------------------------


def handle_host_event(event: HostEvent, state: dict[str, Any] | None = None) -> None:
    """Process a single host event, writing output to stdout or updating state.

    Args:
        event:  The host event to handle.
        state:  Optional mutable dict for accumulating state across events.
                CompleteEvent stores its result under the ``"response"`` key.
    """
    if isinstance(event, StreamTokenEvent):
        sys.stdout.write(event.token)
        sys.stdout.flush()
    elif isinstance(event, StreamThinkingEvent):
        click.echo(click.style(event.thinking, fg="cyan", dim=True), nl=False)
    elif isinstance(event, StreamToolCallStartEvent):
        click.echo(click.style(f"\n⚙ {event.tool_name}", dim=True))
    elif isinstance(event, ToolCallEvent):
        click.echo(click.style(f"\n🔧 {event.tool_name}", bold=True))
        items = list(event.arguments.items())
        display_items = items[:10]
        for key, value in display_items:
            truncated = str(value)[:200]
            click.echo(click.style(f"   {key}: {truncated}", dim=True))
    elif isinstance(event, ToolResultEvent):
        if event.success:
            icon = "✅"
            color: str | None = "green"
        else:
            icon = "❌"
            color = "red"
        click.echo(click.style(f"{icon} {event.tool_name}", fg=color))
        lines = event.output.split("\n")
        display_lines = lines[:10]
        remaining = len(lines) - len(display_lines)
        for line in display_lines:
            click.echo(click.style(f"   {line[:200]}", dim=True))
        if remaining > 0:
            click.echo(click.style(f"   ... ({remaining} more lines)", dim=True))
    elif isinstance(event, TodoUpdateEvent):
        if event.todos:
            total = len(event.todos)
            completed = sum(1 for t in event.todos if t.get("status") == "completed")
            click.echo(click.style(f"\n📋 todos ({completed}/{total})", dim=True))
            symbols: dict[str, str] = {
                "completed": "✓",
                "in_progress": "▶",
                "pending": "○",
            }
            for item in event.todos[:7]:
                s = item.get("status", "pending")
                symbol = symbols.get(s, " ")
                content = str(item.get("content", ""))
                click.echo(click.style(f"   {symbol} {content}", dim=True))
    elif isinstance(event, ChildSessionStartEvent):
        indent = "    " * (event.depth - 1)
        click.echo(
            f"{indent}"
            + click.style(f"⚙ delegate -> {event.agent_name}", fg="cyan", bold=True)
        )
    elif isinstance(event, ChildSessionEvent):
        if event.inner is not None:
            import io

            buf = io.StringIO()
            orig_stdout = sys.stdout
            sys.stdout = buf
            try:
                handle_host_event(event.inner)
            finally:
                sys.stdout = orig_stdout
            output = buf.getvalue()
            indent = "    " * event.depth
            for line in output.split("\n"):
                if line:
                    click.echo(indent + line)
    elif isinstance(event, ChildSessionEndEvent):
        pass
    elif isinstance(event, ErrorEvent):
        click.echo(click.style(f"\nError: {event.message}", fg="red"))
    elif isinstance(event, CompleteEvent):
        sys.stdout.write("\n")
        sys.stdout.flush()
        if state is not None:
            state["response"] = event.result


async def _consume_events(
    host: Host,
    prompt: str,
    event_queue: asyncio.Queue[HostEvent | None],
    cancellation: CancellationState,
) -> None:
    """Consume events from ``host.run()`` and forward them to *event_queue*.

    Tracks the current tool name in *cancellation* so the SIGINT handler
    can tell the user what is still running.  Puts ``None`` as a sentinel
    when the generator is exhausted (or cancelled).
    """
    try:
        async for event in host.run(prompt):
            if isinstance(event, StreamToolCallStartEvent):
                cancellation.current_tool = event.tool_name
            event_queue.put_nowait(event)
            # Yield control so the display task can process the event before
            # we pull the next one from the generator.  Without this, a burst
            # of buffered pipe data causes the consumer to monopolise the
            # event loop and the user sees all output batched at the end.
            await asyncio.sleep(0)
    except asyncio.CancelledError:
        raise
    except (RuntimeError, ConnectionError, OSError):
        # Service processes may die during cancellation (e.g. EOF on pipes).
        # Swallow these so the REPL can continue gracefully.
        if not cancellation.is_cancelled:
            raise
    finally:
        event_queue.put_nowait(None)


# ---------------------------------------------------------------------------
# Prompt session factory
# ---------------------------------------------------------------------------


def _create_prompt_session(history_path: Path | None = None) -> PromptSession:  # type: ignore[type-arg]
    """Create and return a configured PromptSession.

    Args:
        history_path:  Optional path for persistent history via FileHistory.
                       If ``None``, an in-memory history is used.

    Returns:
        A :class:`~prompt_toolkit.PromptSession` configured with:
        - File or in-memory history
        - Ctrl-J to insert a newline (multiline editing)
        - Enter to accept the input
        - Multiline mode enabled
    """
    history = (
        FileHistory(str(history_path))
        if history_path is not None
        else InMemoryHistory()
    )

    bindings = KeyBindings()

    @bindings.add("c-j")
    def _insert_newline(event: Any) -> None:  # noqa: ANN401
        """Ctrl-J inserts a newline (multiline editing)."""
        event.current_buffer.insert_text("\n")

    @bindings.add("enter")
    def _accept(event: Any) -> None:  # noqa: ANN401
        """Enter accepts/submits the current input."""
        event.current_buffer.validate_and_handle()

    session: PromptSession = PromptSession(  # type: ignore[type-arg]
        history=history,
        multiline=True,
        key_bindings=bindings,
    )
    return session


def _build_prompt_html(active_mode: str | None) -> HTML:
    """Return a prompt_toolkit HTML prompt that reflects the active mode.

    Args:
        active_mode: Name of the currently active mode, or ``None``.

    Returns:
        Cyan ``[mode_name]> `` when a mode is active; green ``> `` otherwise.
    """
    if active_mode and isinstance(active_mode, str):
        # Escape any XML-special characters in the mode name to prevent
        # prompt_toolkit's HTML parser from choking (e.g. on test mocks).
        safe = (
            str(active_mode)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        return HTML(f"<ansicyan>[{safe}]&gt; </ansicyan>")
    return HTML("<ansigreen>&gt; </ansigreen>")


# ---------------------------------------------------------------------------
# Slash command handlers
# ---------------------------------------------------------------------------

BANNER = """[bold green]Amplifier Interactive REPL[/bold green]
Type your message and press [bold]Enter[/bold] to send.
Use [bold]Ctrl-J[/bold] for a newline within a message.
Type [bold]/help[/bold] for help, [bold]/exit[/bold] or [bold]/quit[/bold] to exit."""

_HELP_TEXT = """\
Available commands:
  /help                  Show this help message
  /exit  /quit           Exit the REPL
  /status                Show session ID, agent, message count, active mode
  /tools                 List all mounted tools with descriptions
  /config                Show resolved config (orchestrator, services, tools, hooks)
  /agents                List available agents from the definition registry
  /mode [NAME] [on|off]  Set/toggle/clear active mode.  No args = show current.
  /modes                 List all configured modes
  /clear                 Clear the conversation context
  /save [FILENAME]       Save transcript to file (default: transcript_<timestamp>.txt)
  /rename <NAME>         Rename the current session
  /fork [TURN]           Fork the session at turn index TURN (default: all turns)

Dynamic mode shortcuts:
  /<mode_name>           Activate a configured mode by name
  /<mode_name> <text>    Activate mode and immediately send <text> as a prompt

File context injection:
  Use @path/to/file anywhere in your message to inject file content as context.
  The file is read and prepended as a <context_file> block before your message.

Press Enter to send.  Use Ctrl-J to insert a newline within a message.
"""


async def _cmd_status(host: Host, console: Console) -> None:
    """Display a session status panel."""
    try:
        info = host.get_session_info()
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column(style="bold cyan", no_wrap=True)
        table.add_column()
        table.add_row("Session ID", info.get("session_id") or "(not started)")
        table.add_row("Orchestrator", info.get("orchestrator") or "—")
        table.add_row("Provider", info.get("provider") or "—")
        table.add_row("Context Manager", info.get("context_manager") or "—")
        services = info.get("services") or []
        table.add_row("Services", ", ".join(services) if services else "—")
        table.add_row("Messages", str(info.get("message_count", 0)))
        active_mode = info.get("active_mode")
        table.add_row("Active Mode", active_mode or "(none)")
        console.print(Panel(table, title="Session Status", border_style="cyan"))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not get status: {exc}[/yellow]")


async def _cmd_tools(host: Host, console: Console) -> None:
    """List registered tools in a Rich table."""
    try:
        tools = host.get_tools()
        if not tools:
            console.print("[dim]No tools registered yet (run a prompt first).[/dim]")
            return
        table = Table("Name", "Description", show_header=True, header_style="bold")
        for t in tools:
            desc = t.get("description") or ""
            if len(desc) > 80:
                desc = desc[:77] + "…"
            table.add_row(t.get("name", ""), desc)
        console.print(table)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not list tools: {exc}[/yellow]")


async def _cmd_config(host: Host, console: Console) -> None:
    """Display the resolved configuration as a panel."""
    try:
        cfg = host.get_config_summary()
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column(style="bold cyan", no_wrap=True)
        table.add_column()
        table.add_row("Orchestrator", cfg.get("orchestrator") or "—")
        table.add_row("Provider", cfg.get("provider") or "—")
        table.add_row("Context Manager", cfg.get("context_manager") or "—")
        services = cfg.get("services") or []
        table.add_row("Services", ", ".join(services) if services else "—")
        tools = cfg.get("tools") or []
        hooks = cfg.get("hooks") or []
        table.add_row("Tools", f"{len(tools)} registered" if tools else "(none)")
        table.add_row("Hooks", f"{len(hooks)} registered" if hooks else "(none)")
        cc = cfg.get("component_config") or {}
        if cc:
            table.add_row("Component Config", ", ".join(sorted(cc.keys())))
        console.print(Panel(table, title="Configuration", border_style="blue"))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not get config: {exc}[/yellow]")


async def _cmd_agents(host: Host, console: Console) -> None:
    """List available agents from the definition registry."""
    try:
        agents = host.get_agents()
        if not agents:
            console.print("[dim]No agents found in the definition registry.[/dim]")
            return
        table = Table("Name", "Definition ID", show_header=True, header_style="bold")
        for a in agents:
            table.add_row(a.get("name", ""), a.get("definition_id", ""))
        console.print(table)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not list agents: {exc}[/yellow]")


async def _cmd_mode(host: Host, console: Console, args: str, rest: str) -> None:
    """Handle ``/mode [NAME] [on|off]``."""
    try:
        if not args:
            current = host.get_active_mode()
            if current:
                console.print(f"[cyan]Active mode:[/cyan] [bold]{current}[/bold]")
            else:
                console.print("[dim]No active mode.[/dim]")
            return

        mode_name = args.strip()
        flag = rest.strip().lower()

        # Explicit "off" / "clear" / "none" as the name → clear
        if mode_name.lower() in ("off", "none", "clear"):
            await host.set_mode(None)
            console.print("[dim]Mode cleared.[/dim]")
            return

        if flag == "off":
            current = host.get_active_mode()
            if current and current.lower() == mode_name.lower():
                await host.set_mode(None)
                console.print("[dim]Mode cleared.[/dim]")
            else:
                console.print(f"[dim]Mode '{mode_name}' was not active.[/dim]")
        else:
            # flag is "on" or empty — activate
            await host.set_mode(mode_name)
            console.print(f"[cyan]Mode set:[/cyan] [bold]{mode_name}[/bold]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not set mode: {exc}[/yellow]")


async def _cmd_modes(host: Host, console: Console) -> None:
    """List configured modes with an active indicator."""
    try:
        modes = host.get_available_modes()
        active = host.get_active_mode()
        if not modes:
            console.print(
                "[dim]No modes configured.  "
                "Add modes via component_config or a modes service.[/dim]"
            )
            return
        table = Table("Mode", "Active", show_header=True, header_style="bold")
        for m in modes:
            name = m.get("name", "")
            marker = "✓" if active and active.lower() == name.lower() else ""
            table.add_row(name, marker)
        console.print(table)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not list modes: {exc}[/yellow]")


async def _cmd_clear(host: Host, console: Console) -> None:
    """Clear conversation context."""
    try:
        await host.clear_context()
        console.print("[dim]Conversation context cleared.[/dim]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not clear context: {exc}[/yellow]")


async def _cmd_save(host: Host, console: Console, filename_arg: str) -> None:
    """Save session transcript to a file."""
    filename = filename_arg or f"transcript_{datetime.now():%Y%m%d_%H%M%S}.txt"
    try:
        persistence = host._persistence  # noqa: SLF001
        if persistence is None:
            console.print("[yellow]No session in progress — nothing to save.[/yellow]")
            return
        messages = persistence.load_transcript()
        if not messages:
            console.print("[yellow]Transcript is empty.[/yellow]")
            return
        out_path = Path(filename)
        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                content = "\n".join(text_parts)
            lines.append(f"[{role}]\n{content}\n")
        out_path.write_text("\n".join(lines), encoding="utf-8")
        console.print(
            f"[green]Transcript ({len(messages)} messages) saved to "
            f"[bold]{out_path}[/bold][/green]"
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not save transcript: {exc}[/yellow]")


async def _cmd_rename(host: Host, console: Console, name_arg: str) -> None:
    """Rename the current session."""
    if not name_arg:
        console.print("[yellow]Usage: /rename <NAME>[/yellow]")
        return
    try:
        persistence = host._persistence  # noqa: SLF001
        if persistence is None:
            console.print("[yellow]No session in progress.[/yellow]")
            return
        metadata: dict[str, Any] = {}
        if persistence.metadata_path.exists():
            with persistence.metadata_path.open(encoding="utf-8") as fh:
                metadata = json.load(fh)
        metadata["name"] = name_arg
        persistence.save_metadata(metadata)
        console.print(f"[green]Session renamed to '[bold]{name_arg}[/bold]'.[/green]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not rename session: {exc}[/yellow]")


async def _cmd_fork(host: Host, console: Console, turn_arg: str) -> None:
    """Fork the session at an optional turn index."""
    try:
        persistence = host._persistence  # noqa: SLF001
        if persistence is None:
            console.print("[yellow]No session in progress.[/yellow]")
            return

        messages = persistence.load_transcript()
        turn_count: int | None = None
        if turn_arg:
            try:
                turn_count = int(turn_arg)
            except ValueError:
                console.print(
                    "[yellow]Usage: /fork [TURN]  (TURN is an integer)[/yellow]"
                )
                return
            messages = messages[:turn_count]

        from amplifier_ipc.host.persistence import SessionPersistence  # noqa: PLC0415

        fork_id = uuid.uuid4().hex[:16]
        # sessions base dir is the parent of the current session directory
        base_dir = persistence._session_dir.parent  # noqa: SLF001
        fork_p = SessionPersistence(fork_id, base_dir)
        for msg in messages:
            fork_p.append_message(msg)
        fork_p.save_metadata(
            {
                "session_id": fork_id,
                "forked_from": host.session_id,
                "forked_at_turn": turn_count,
                "forked_at": datetime.now().isoformat(),
            }
        )
        console.print(
            f"[green]Session forked → [bold]{fork_id}[/bold] "
            f"({len(messages)} messages copied).[/green]"
        )
        console.print(f"  Resume with: [cyan]amplifier-ipc run -s {fork_id[:8]}[/cyan]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not fork session: {exc}[/yellow]")


async def _dispatch_slash(
    raw: str,
    host: Host,
    console: Console,
    available_modes: list[dict],
) -> tuple[str | None, bool]:
    """Dispatch a slash command to the appropriate handler.

    Args:
        raw:             The full slash command string (e.g. ``"/mode debug on"``).
        host:            The active :class:`Host` instance.
        console:         Rich console for output.
        available_modes: Currently known modes for dynamic shortcut resolution.

    Returns:
        ``(inline_prompt, should_exit)`` where:

        * *inline_prompt* — if not ``None``, the REPL should process this
          string as the next prompt without reading from the user (used by
          mode shortcuts with trailing text).
        * *should_exit* — if ``True``, the REPL should exit.
    """
    # Split into at most 3 tokens: command  first-arg  remainder
    parts = raw.split(None, 2)
    command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    rest = parts[2] if len(parts) > 2 else ""

    if command in ("/exit", "/quit"):
        console.print("[dim]Goodbye![/dim]")
        return None, True

    elif command == "/help":
        console.print(_HELP_TEXT)

    elif command == "/status":
        await _cmd_status(host, console)

    elif command == "/tools":
        await _cmd_tools(host, console)

    elif command == "/config":
        await _cmd_config(host, console)

    elif command == "/agents":
        await _cmd_agents(host, console)

    elif command == "/mode":
        await _cmd_mode(host, console, args, rest)

    elif command == "/modes":
        await _cmd_modes(host, console)

    elif command == "/clear":
        await _cmd_clear(host, console)

    elif command == "/save":
        await _cmd_save(host, console, args)

    elif command == "/rename":
        # Name may contain spaces — join args and rest
        name = (args + (" " + rest if rest else "")).strip()
        await _cmd_rename(host, console, name)

    elif command == "/fork":
        await _cmd_fork(host, console, args)

    else:
        # Dynamic mode shortcut: /<mode_name> [trailing text]
        mode_name = command.lstrip("/")
        matched = any(m.get("name", "").lower() == mode_name for m in available_modes)
        if matched:
            try:
                await host.set_mode(mode_name)
                console.print(f"[cyan]Mode set:[/cyan] [bold]{mode_name}[/bold]")
            except Exception as exc:  # noqa: BLE001
                console.print(f"[yellow]Could not set mode: {exc}[/yellow]")
            # Any trailing text becomes the next inline prompt
            trailing = (args + (" " + rest if rest else "")).strip()
            if trailing:
                return trailing, False
        else:
            console.print(f"[yellow]Unknown command: {command}[/yellow]")

    return None, False


# ---------------------------------------------------------------------------
# Main REPL entrypoint
# ---------------------------------------------------------------------------


async def interactive_repl(
    host: Host,
    agent_name: str = "",
    console: Console | None = None,
) -> None:
    """Run an interactive REPL loop for multi-turn conversations.

    Features:

    * **Slash commands**: ``/help``, ``/exit``, ``/quit``, ``/status``,
      ``/tools``, ``/config``, ``/agents``, ``/mode``, ``/modes``,
      ``/clear``, ``/save``, ``/rename``, ``/fork``.
    * **Dynamic mode shortcuts**: ``/<mode_name>`` activates the named mode;
      trailing text is sent as the first prompt in that mode.
    * **Mode indicator**: prompt shows ``[mode_name]> `` (cyan) when a mode
      is active, plain ``> `` (green) otherwise.
    * **File context injection**: ``@path/to/file`` in a message is expanded
      to a ``<context_file>`` block before the prompt is sent.

    Args:
        host:        The :class:`~amplifier_ipc.host.Host` instance.
        agent_name:  Agent name displayed in the banner.
        console:     Optional Rich :class:`~rich.console.Console` for output.
                     Defaults to a new stderr console.
    """
    if console is None:
        console = Console(stderr=True)

    # Display welcome banner
    title = f"Amplifier REPL — {agent_name}" if agent_name else "Amplifier REPL"
    console.print(Panel(BANNER, title=title, border_style="green"))

    # Try to use persistent history
    try:
        from amplifier_ipc.cli.paths import get_repl_history_path  # noqa: PLC0415

        history_path = get_repl_history_path()
        history_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        history_path = None

    prompt_session = _create_prompt_session(history_path=history_path)

    # Load available modes at startup; refreshed after every turn so that
    # a modes service can register/unregister modes dynamically.
    available_modes: list[dict] = []
    try:
        available_modes = host.get_available_modes()
    except Exception:  # noqa: BLE001
        pass

    # When a mode shortcut is invoked with trailing text (e.g.
    # "/brainstorm write a story"), the text is queued here and sent as
    # the next prompt without reading from the user.
    _pending_prompt: str | None = None

    while True:
        # ---- Determine input ------------------------------------------------
        if _pending_prompt is not None:
            user_input = _pending_prompt
            _pending_prompt = None
        else:
            # Refresh the active mode so the prompt indicator stays current
            try:
                active_mode: str | None = host.get_active_mode()
            except Exception:  # noqa: BLE001
                active_mode = None

            try:
                user_input = await prompt_session.prompt_async(
                    _build_prompt_html(active_mode),
                )
            except EOFError:
                console.print("\n[dim]Goodbye![/dim]")
                break
            except KeyboardInterrupt:
                # Ctrl+C at prompt — confirm exit to prevent accidental exits
                console.print()
                try:
                    if click.confirm("Exit session?", default=False):
                        console.print("[dim]Goodbye![/dim]")
                        break
                except (KeyboardInterrupt, EOFError):
                    console.print("\n[dim]Goodbye![/dim]")
                    break
                continue

        user_input = user_input.strip()
        if not user_input:
            continue

        # Bare "exit" / "quit" (without slash) — matches amplifier-app-cli
        if user_input.lower() in ("exit", "quit"):
            console.print("[dim]Goodbye![/dim]")
            break

        # ---- Handle slash commands ------------------------------------------
        if user_input.startswith("/"):
            inline, should_exit = await _dispatch_slash(
                user_input, host, console, available_modes
            )
            if should_exit:
                break
            if inline is not None:
                _pending_prompt = inline
            continue

        # ---- @mention file injection ----------------------------------------
        user_input = _process_mentions(user_input, console)

        # ---- Execute prompt with two-stage Ctrl+C cancellation --------------
        from amplifier_ipc.cli.streaming import StreamingDisplay  # noqa: PLC0415

        cancellation = CancellationState()
        event_queue: asyncio.Queue[HostEvent | None] = asyncio.Queue()
        display = StreamingDisplay(console)

        def _sigint_handler(signum: int, frame: Any) -> None:  # noqa: ANN401
            if cancellation.is_cancelled:
                cancellation.request_immediate()
                console.print("\n[bold red]Cancelling immediately...[/bold red]")
            else:
                cancellation.request_graceful()
                tool = cancellation.current_tool
                if tool:
                    console.print(
                        f"\n[yellow]Cancelling after [bold]{tool}[/bold] "
                        "completes... (Ctrl+C again to force)[/yellow]"
                    )
                else:
                    console.print(
                        "\n[yellow]Cancelling after current operation "
                        "completes... (Ctrl+C again to force)[/yellow]"
                    )

        original_handler = signal.signal(signal.SIGINT, _sigint_handler)

        try:
            task = asyncio.create_task(
                _consume_events(host, user_input, event_queue, cancellation)
            )

            while True:
                if cancellation.is_immediate:
                    task.cancel()
                    break

                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.05)
                except TimeoutError:
                    if task.done():
                        break
                    continue

                if event is None:
                    break

                if isinstance(event, ApprovalRequestEvent):
                    handler = CLIApprovalHandler(console)
                    approved = await handler.handle_approval(event)
                    host.send_approval(approved)
                else:
                    display.handle_event(event)

            try:
                await task
            except asyncio.CancelledError:
                console.print("\n[yellow]Cancelled.[/yellow]")

        finally:
            signal.signal(signal.SIGINT, original_handler)

        # Render the final response if available
        if display.response:
            render_message(
                {"role": "assistant", "content": display.response},
                console,
            )

        # Refresh available modes after each turn — a modes service may have
        # registered new modes or changed available sets during the turn.
        try:
            available_modes = host.get_available_modes()
        except Exception:  # noqa: BLE001
            pass

    # ---- Exit message with session resume info ------------------------------
    session_id = host.session_id
    if session_id:
        agent_flag = f" -a {agent_name}" if agent_name else ""
        console.print(
            "\n[yellow]Session exited - resume anytime with these commands:[/yellow]"
        )
        console.print(
            "  [cyan]amplifier-ipc session list[/cyan]  # interactive list of sessions"
        )
        console.print(
            f"  [cyan]amplifier-ipc run{agent_flag} -s {session_id[:8]}[/cyan]  "
            "# jump directly to this session"
        )
        console.print()
