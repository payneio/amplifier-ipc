"""Run command — launches an agent session."""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from amplifier_ipc.cli.key_manager import KeyManager
from amplifier_ipc.cli.session_launcher import launch_session, list_registered_agents
from amplifier_ipc.cli.streaming import StreamingDisplay
from amplifier_ipc.host.definition_registry import Registry
from amplifier_ipc.host.events import ApprovalRequestEvent


# ---------------------------------------------------------------------------
# Agent name resolution
# ---------------------------------------------------------------------------


def _resolve_agent_name(agent: str | None) -> str:
    """Resolve the agent name to use for the session.

    Resolution order:
    1. Explicit ``--agent`` CLI flag (already provided as *agent*).
    2. ``default_agent`` key in the merged AppSettings.
    3. Exactly one agent registered → use it automatically (prints a notice).
    4. Multiple agents registered → list them and exit with an error.
    5. No agents registered → guide the user to ``discover`` / ``init``.

    Args:
        agent: Value supplied by the ``--agent`` CLI flag, or ``None``.

    Returns:
        The resolved agent name string.

    Raises:
        SystemExit: When no unambiguous agent can be determined.
    """
    if agent is not None:
        return agent

    # --- 2. settings default_agent -----------------------------------------
    from amplifier_ipc.cli.settings import get_settings

    settings = get_settings()
    default = settings.get_merged_settings().get("default_agent")
    if default:
        return str(default)

    # --- 3-5. registry probe --------------------------------------------------
    registry = Registry()
    agent_names = list_registered_agents(registry)

    if len(agent_names) == 1:
        click.echo(
            "No --agent specified; using the only registered agent: "
            + click.style(agent_names[0], bold=True),
            err=True,
        )
        return agent_names[0]

    if len(agent_names) > 1:
        click.echo(
            "Multiple agents are registered. Specify one with --agent / -a:",
            err=True,
        )
        for name in sorted(agent_names):
            click.echo(f"  {name}", err=True)
        click.echo(
            "\nTip: set a permanent default with:\n"
            "  amplifier-ipc config set default_agent <name>",
            err=True,
        )
        raise SystemExit(1)

    # No agents registered
    click.echo(
        "No agents are registered.\n"
        "  • Run 'amplifier-ipc discover' to discover agents from a registry.\n"
        "  • Run 'amplifier-ipc init' to set up a new project.",
        err=True,
    )
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Core async implementation
# ---------------------------------------------------------------------------


async def _run_agent(
    agent_name_arg: str | None,
    message: str | None,
    behaviors: list[str],
    session: str | None,
    project: str | None,
    working_dir: str | None,
    provider: str | None,
    model: str | None,
    max_tokens: int | None,
    verbose: bool,
    output_format: str,
) -> None:
    """Async implementation of the run command.

    Loads API keys, resolves the agent, launches a session, then either
    executes a single-shot prompt (with optional JSON output) or enters an
    interactive REPL.

    Args:
        agent_name_arg: Value of the ``--agent`` flag, or ``None``.
        message: Positional MESSAGE argument, or ``None``.
        behaviors: Extra behaviors supplied via ``--add-behavior``.
        session: Session ID to resume (``--session``), or ``None``.
        project: Project name (``--project``), unused by Host directly.
        working_dir: Working directory override (``--working-dir``), unused directly.
        provider: Provider override (``--provider``), or ``None``.
        model: Model override (``--model``), or ``None``.
        max_tokens: Maximum output tokens (``--max-tokens``), or ``None``.
        verbose: Whether verbose output is enabled (``--verbose``).
        output_format: One of ``"text"``, ``"json"``, or ``"json-trace"``.
    """
    is_json_output = output_format in ("json", "json-trace")
    is_pipe = not sys.stdin.isatty()

    # ---- B. Default agent resolution (before pipe detection) --------------
    # Agent resolution must happen first so that a missing --agent flag
    # produces the right error rather than a "piped stdin empty" message
    # (test runners / CI are non-TTY).
    agent_name = _resolve_agent_name(agent_name_arg)

    # ---- E. stdin pipe detection ------------------------------------------
    # If stdin is piped (non-TTY) and no explicit MESSAGE was given, read the
    # message from stdin.  In pipe mode we never enter the interactive REPL.
    if is_pipe and message is None:
        piped_input = sys.stdin.read().strip()
        if piped_input:
            message = piped_input
        else:
            _emit_error(
                is_json_output,
                "Piped stdin is empty and no MESSAGE argument was provided.",
                "ValueError",
                None,
            )
            raise SystemExit(1)

    # ---- Console creation ------------------------------------------------
    # For JSON output formats we redirect all Rich output to stderr so that
    # stdout carries only the machine-readable JSON payload.
    if is_json_output:
        console = Console(stderr=True)
    else:
        console = Console()

    km = KeyManager()
    km.load_keys()

    session_id: str | None = None

    try:
        # ---- A. Launch session with overrides ----------------------------
        if verbose and not is_json_output:
            console.print(f"[dim]Launching session: agent={agent_name}[/dim]")

        host = await launch_session(
            agent_name,
            extra_behaviors=behaviors if behaviors else None,
            provider_override=provider,
            model_override=model,
            max_tokens=max_tokens,
            verbose=verbose,
            working_dir=Path(working_dir) if working_dir else Path.cwd(),
        )

        if session is not None:
            host.set_resume_session_id(session)

        if verbose and not is_json_output:
            console.print("[dim]Session ready.[/dim]")

        if message is not None:
            # ----------------------------------------------------------
            # Single-shot mode: run one prompt, stream events, output result
            # ----------------------------------------------------------
            display = StreamingDisplay(
                console,
                trace_mode=(output_format == "json-trace"),
                verbose=verbose,
            )

            async for event in host.run(message):
                if isinstance(event, ApprovalRequestEvent):
                    host.send_approval(True)
                else:
                    display.handle_event(event)

            session_id = host.session_id

            # ---- C/D. JSON output ----------------------------------------
            if is_json_output:
                result: dict[str, Any] = {
                    "status": "success",
                    "response": display.response or "",
                    "session_id": session_id or "",
                    "agent": agent_name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                if output_format == "json-trace":
                    result["execution_trace"] = display.trace
                    result["metadata"] = display.trace_metadata
                sys.stdout.write(json.dumps(result) + "\n")
                sys.stdout.flush()

        else:
            # ----------------------------------------------------------
            # Interactive REPL mode (not entered when stdin is a pipe)
            # ----------------------------------------------------------
            if is_pipe:
                # Shouldn't reach here — handled above — but guard anyway.
                _emit_error(
                    is_json_output,
                    "Cannot enter REPL: stdin is a pipe.",
                    "RuntimeError",
                    None,
                )
                raise SystemExit(1)

            from amplifier_ipc.cli.repl import interactive_repl

            await interactive_repl(host, agent_name=agent_name, console=console)

    except SystemExit:
        raise
    except Exception as exc:
        session_id = session_id  # may have been set before the exception

        if is_json_output:
            _emit_error(
                is_json_output,
                str(exc),
                type(exc).__name__,
                session_id,
            )
            raise SystemExit(1)
        elif verbose:
            # ---- F. Verbose flag: show full traceback on error --------
            traceback.print_exc()
            raise
        else:
            raise


def _emit_error(
    is_json_output: bool,
    message: str,
    error_type: str,
    session_id: str | None,
) -> None:
    """Write a JSON error payload to stdout (json mode) or stderr (text mode).

    Args:
        is_json_output: True when the ``--output-format`` is json/json-trace.
        message: Human-readable error description.
        error_type: Exception class name string.
        session_id: Session ID if available, otherwise ``None``.
    """
    if is_json_output:
        payload: dict[str, Any] = {
            "status": "error",
            "error": message,
            "error_type": error_type,
            "session_id": session_id or "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()
    else:
        click.echo(f"Error: {message}", err=True)


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------


@click.command()
@click.option(
    "--agent",
    "-a",
    default=None,
    help=(
        "Agent name to run.  If omitted, the default_agent from settings is used; "
        "if exactly one agent is registered it is selected automatically."
    ),
)
@click.option(
    "--add-behavior",
    "-b",
    multiple=True,
    help="Additional behavior to add (can be used multiple times).",
)
@click.option("--session", "-s", default=None, help="Session ID to resume.")
@click.option("--project", default=None, help="Project name.")
@click.option("--working-dir", "-w", default=None, help="Working directory.")
@click.option(
    "--provider",
    "-p",
    default=None,
    help="Override the provider for this session (e.g. 'anthropic', 'openai').",
)
@click.option(
    "--model",
    "-m",
    default=None,
    help=(
        "Override the model for this session.  Requires --provider or a configured "
        "default provider."
    ),
)
@click.option(
    "--max-tokens",
    default=None,
    type=int,
    help="Maximum number of output tokens for the session.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help=(
        "Enable verbose output: show full tracebacks on errors, expand tool "
        "call/result truncation limits, and display service startup detail."
    ),
)
@click.option(
    "--output-format",
    "-o",
    default="text",
    type=click.Choice(["text", "json", "json-trace"], case_sensitive=False),
    help=(
        "Output format.  'text' (default) renders with Rich.  "
        "'json' suppresses Rich output and prints a JSON result object to stdout.  "
        "'json-trace' extends 'json' with a full execution_trace array."
    ),
)
@click.argument("message", required=False)
def run(
    agent: str | None,
    add_behavior: tuple[str, ...],
    session: str | None,
    project: str | None,
    working_dir: str | None,
    provider: str | None,
    model: str | None,
    max_tokens: int | None,
    verbose: bool,
    output_format: str,
    message: str | None,
) -> None:
    """Run an agent session.

    If MESSAGE is provided, executes a single-shot prompt and exits.
    Otherwise, enters an interactive REPL (unless stdin is a pipe, in which
    case the message is read from stdin and a single-shot run is performed).

    \b
    Examples:
      # Interactive REPL with the default agent
      amplifier-ipc run

      # Single-shot with explicit agent
      amplifier-ipc run -a my-agent "What is 2+2?"

      # JSON output for scripting
      amplifier-ipc run -a my-agent -o json "Summarise the README"

      # JSON trace for debugging
      amplifier-ipc run -a my-agent -o json-trace "Do something complex"

      # Provider / model override
      amplifier-ipc run -a my-agent -p openai -m gpt-4o "Hello"

      # Piped input
      echo "Explain this code" | amplifier-ipc run -o json
    """
    asyncio.run(
        _run_agent(
            agent,
            message,
            list(add_behavior),
            session,
            project,
            working_dir,
            provider,
            model,
            max_tokens,
            verbose,
            output_format,
        )
    )
