"""Entry point for amplifier-browser-tester IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier_browser_tester IPC service."""
    Server("amplifier_browser_tester").run()


if __name__ == "__main__":
    main()
