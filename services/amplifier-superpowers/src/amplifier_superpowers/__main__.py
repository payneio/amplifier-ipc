"""Entry point for amplifier-superpowers IPC service."""

from __future__ import annotations

from amplifier_ipc.protocol import Server


def main() -> None:
    """Start the amplifier_superpowers IPC service."""
    Server("amplifier_superpowers").run()


if __name__ == "__main__":
    main()
