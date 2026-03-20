"""Entry point for amplifier-skills IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier-skills IPC service."""
    Server("amplifier_skills").run()


if __name__ == "__main__":
    main()
