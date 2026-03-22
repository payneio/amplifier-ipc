"""Entry point for amplifier-filesystem IPC service."""

from __future__ import annotations

from amplifier_ipc.protocol import Server


def main() -> None:
    """Start the amplifier_filesystem IPC service."""
    Server("amplifier_filesystem").run()


if __name__ == "__main__":
    main()
