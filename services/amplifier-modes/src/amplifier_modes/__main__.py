"""Entry point for amplifier-modes IPC service."""

from __future__ import annotations

from amplifier_ipc.protocol import Server


def main() -> None:
    """Start the amplifier-modes IPC service."""
    Server("amplifier_modes").run()


if __name__ == "__main__":
    main()
