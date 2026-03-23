"""Interactive REPL for agent sessions."""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path
from typing import Any

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.panel import Panel

from amplifier_ipc.host.events import (
    ApprovalRequestEvent,
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)
from amplifier_ipc.host.host import Host

from amplifier_ipc.cli.approval_provider import CLIApprovalHandler
from amplifier_ipc.cli.ui.message_renderer import render_message


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
        - A green ``"> "`` prompt
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


BANNER = """[bold green]Amplifier Interactive REPL[/bold green]
Type your message and press [bold]Enter[/bold] to send.
Use [bold]Ctrl-J[/bold] for a newline within a message.
Type [bold]/help[/bold] for help, [bold]/exit[/bold] or [bold]/quit[/bold] to exit."""

_HELP_TEXT = """\
Available commands:
  /help   Show this help message
  /exit   Exit the REPL
  /quit   Exit the REPL

Press Enter to send your message.
Use Ctrl-J to insert a newline within a message.
"""


async def interactive_repl(
    host: Host,
    agent_name: str = "",
    console: Console | None = None,
) -> None:
    """Run an interactive REPL loop for multi-turn conversations.

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
        from amplifier_ipc.cli.paths import get_repl_history_path

        history_path = get_repl_history_path()
        history_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        history_path = None

    prompt_session = _create_prompt_session(history_path=history_path)

    while True:
        # ---- Read user input ------------------------------------------------
        try:
            user_input: str = await prompt_session.prompt_async(
                HTML("<ansigreen>&gt; </ansigreen>"),
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
            command = user_input.lower().split()[0]
            if command in ("/exit", "/quit"):
                console.print("[dim]Goodbye![/dim]")
                break
            elif command == "/help":
                console.print(_HELP_TEXT)
                continue
            else:
                console.print(f"[yellow]Unknown command: {command}[/yellow]")
                continue

        # ---- Execute prompt with two-stage Ctrl+C cancellation --------------
        cancellation = CancellationState()
        event_queue: asyncio.Queue[HostEvent | None] = asyncio.Queue()
        state: dict[str, Any] = {}

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
                    event = await asyncio.wait_for(
                        event_queue.get(), timeout=0.05
                    )
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
                    handle_host_event(event, state=state)

            try:
                await task
            except asyncio.CancelledError:
                console.print("\n[yellow]Cancelled.[/yellow]")

        finally:
            signal.signal(signal.SIGINT, original_handler)

        # Render the final response if available
        response = state.get("response")
        if response:
            render_message(
                {"role": "assistant", "content": response},
                console,
            )

    # ---- Exit message with session resume info ------------------------------
    session_id = host.session_id
    if session_id:
        agent_flag = f" -a {agent_name}" if agent_name else ""
        console.print(
            "\n[yellow]Session exited - resume anytime with these commands:[/yellow]"
        )
        console.print(
            "  [cyan]amplifier-ipc session list[/cyan]  "
            "# interactive list of sessions"
        )
        console.print(
            f"  [cyan]amplifier-ipc run{agent_flag} -s {session_id[:8]}[/cyan]  "
            "# jump directly to this session"
        )
        console.print()
