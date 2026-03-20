"""Entry point for amplifier-design-intelligence IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier_design_intelligence IPC service."""
    Server("amplifier_design_intelligence").run()


if __name__ == "__main__":
    main()
