"""CLI entry point for amplifier-ipc-host.

Usage::

    amplifier-ipc-host run session.yaml
    amplifier-ipc-host run session.yaml --prompt "What is 2+2?"
    echo "What is 2+2?" | amplifier-ipc-host run session.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from amplifier_ipc_host.config import load_settings, parse_session_config
from amplifier_ipc_host.events import CompleteEvent, StreamTokenEvent
from amplifier_ipc_host.host import Host


async def _consume_events(host: Host, prompt: str) -> None:
    """Consume the host event stream and print output to stdout.

    Stream tokens are printed immediately as they arrive.  The final
    :class:`~amplifier_ipc_host.events.CompleteEvent` result is printed if no
    stream tokens were emitted (i.e. non-streaming orchestrators).

    Args:
        host: Configured :class:`Host` instance ready to run.
        prompt: User prompt to send to the orchestrator.
    """
    streamed = False
    async for event in host.run(prompt):
        if isinstance(event, StreamTokenEvent):
            sys.stdout.write(event.token)
            sys.stdout.flush()
            streamed = True
        elif isinstance(event, CompleteEvent):
            if streamed:
                # End the streaming output with a newline
                sys.stdout.write("\n")
                sys.stdout.flush()
            else:
                # No streaming tokens — print the complete result
                print(event.result)


def _run_session(config_path: Path, prompt: str | None) -> None:
    """Load config, resolve prompt, run a session, and print the response.

    Args:
        config_path: Path to the session YAML configuration file.
        prompt: Optional prompt string.  If *None*, the user is asked to enter
            a prompt on stdin (terminated with Ctrl+D / EOF).
    """
    config = parse_session_config(config_path)
    settings = load_settings(
        user_settings_path=Path.home() / ".amplifier" / "settings.yaml",
        project_settings_path=Path(".amplifier") / "settings.yaml",
    )

    if prompt is None:
        print("Enter prompt (Ctrl+D to send):", file=sys.stderr)
        resolved: str = sys.stdin.read()
    else:
        resolved = prompt

    resolved = resolved.strip()
    if not resolved:
        print("Error: prompt must not be empty", file=sys.stderr)
        sys.exit(1)

    host = Host(config=config, settings=settings)
    asyncio.run(_consume_events(host, resolved))


def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate subcommand."""
    parser = argparse.ArgumentParser(
        prog="amplifier-ipc-host",
        description="Amplifier IPC host — run a session against configured services.",
    )

    subparsers = parser.add_subparsers(dest="subcommand")
    subparsers.required = True

    run_parser = subparsers.add_parser(
        "run",
        help="Execute a session from a YAML configuration file.",
    )
    run_parser.add_argument(
        "session_config",
        type=Path,
        help="Path to the session YAML configuration file.",
    )
    run_parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Prompt to send to the orchestrator.  Reads from stdin if omitted.",
    )

    args = parser.parse_args()

    if args.subcommand == "run":
        _run_session(args.session_config, args.prompt)


if __name__ == "__main__":
    main()
