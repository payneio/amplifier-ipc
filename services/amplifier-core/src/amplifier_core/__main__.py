"""Entry point for amplifier-core IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier_core IPC service."""
    Server("amplifier_core").run()


if __name__ == "__main__":
    main()
