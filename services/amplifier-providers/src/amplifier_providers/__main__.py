"""Entry point for amplifier-providers IPC service."""

from __future__ import annotations

from amplifier_ipc.protocol import Server


def main() -> None:
    """Start the amplifier-providers IPC service."""
    Server("amplifier_providers").run()


if __name__ == "__main__":
    main()
