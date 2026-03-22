"""Interactive REPL for agent sessions."""

from __future__ import annotations

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

    session = _create_prompt_session(history_path=history_path)

    while True:
        try:
            user_input: str = await session.prompt_async(
                HTML("<ansigreen>&gt; </ansigreen>"),
            )
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Handle slash commands
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

        # Execute the prompt and stream events
        state: dict[str, Any] = {}
        async for event in host.run(user_input):
            if isinstance(event, ApprovalRequestEvent):
                handler = CLIApprovalHandler(console)
                approved = await handler.handle_approval(event)
                host.send_approval(approved)
            else:
                handle_host_event(event, state=state)

        # Render the final response if available
        response = state.get("response")
        if response:
            render_message(
                {"role": "assistant", "content": response},
                console,
            )
