"""Entry point for amplifier-amplifier IPC service."""

from __future__ import annotations

from amplifier_ipc.protocol import Server


def main() -> None:
    """Start the amplifier_amplifier IPC service."""
    Server("amplifier_amplifier").run()


if __name__ == "__main__":
    main()
