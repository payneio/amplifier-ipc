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
from amplifier_ipc_host.host import Host


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
    response = asyncio.run(host.run(resolved))
    print(response)


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
