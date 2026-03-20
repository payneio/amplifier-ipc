"""Entry point for amplifier-routing-matrix IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier-routing-matrix IPC service."""
    Server("amplifier_routing_matrix").run()


if __name__ == "__main__":
    main()
