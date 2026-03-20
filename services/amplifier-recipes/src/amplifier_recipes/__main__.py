"""Entry point for amplifier-recipes IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier_recipes IPC service."""
    Server("amplifier_recipes").run()


if __name__ == "__main__":
    main()
