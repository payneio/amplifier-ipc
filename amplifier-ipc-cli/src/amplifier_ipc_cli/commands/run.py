"""Run command — launches an agent session."""

from __future__ import annotations

import asyncio
import sys

import click

from amplifier_ipc_cli.key_manager import KeyManager
from amplifier_ipc_cli.session_launcher import launch_session
from amplifier_ipc_host.events import (
    ApprovalRequestEvent,
    CompleteEvent,
    HostEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)


def _handle_event(event: HostEvent) -> None:
    """Handle a single host event, writing output to stdout."""
    if isinstance(event, StreamTokenEvent):
        sys.stdout.write(event.token)
        sys.stdout.flush()
    elif isinstance(event, StreamThinkingEvent):
        click.echo(click.style(event.thinking, fg="cyan", dim=True), nl=False)
    elif isinstance(event, StreamToolCallStartEvent):
        click.echo(click.style(event.tool_name, dim=True), nl=False)
    elif isinstance(event, CompleteEvent):
        click.echo()  # newline after completion


async def _run_agent(
    agent_name: str,
    message: str | None,
    behaviors: list[str],
    session: str | None,
    project: str | None,
    working_dir: str | None,
) -> None:
    """Async implementation of the run command.

    Loads API keys, launches a session, then either executes a single-shot
    prompt or enters an interactive REPL.
    """
    km = KeyManager()
    km.load_keys()

    host = await launch_session(
        agent_name, extra_behaviors=behaviors if behaviors else None
    )

    if message is not None:
        # Single-shot mode: run one prompt and stream events
        async for event in host.run(message):
            if isinstance(event, ApprovalRequestEvent):
                host.send_approval(True)
            else:
                _handle_event(event)
    else:
        # Interactive REPL mode
        from amplifier_ipc_cli.repl import interactive_repl

        await interactive_repl(host)


@click.command()
@click.option("--agent", "-a", required=True, help="Agent name to run.")
@click.option(
    "--add-behavior",
    "-b",
    multiple=True,
    help="Additional behavior to add (can be used multiple times).",
)
@click.option("--session", "-s", default=None, help="Session ID to resume.")
@click.option("--project", default=None, help="Project name.")
@click.option("--working-dir", "-w", default=None, help="Working directory.")
@click.argument("message", required=False)
def run(
    agent: str,
    add_behavior: tuple[str, ...],
    session: str | None,
    project: str | None,
    working_dir: str | None,
    message: str | None,
) -> None:
    """Run an agent session.

    If MESSAGE is provided, executes a single-shot prompt.
    Otherwise, enters an interactive REPL.
    """
    asyncio.run(
        _run_agent(
            agent,
            message,
            list(add_behavior),
            session,
            project,
            working_dir,
        )
    )
