"""Entry point for amplifier-foundation IPC service.

Run as a subprocess by amplifier-ipc-host; communicates over stdin/stdout
using the amplifier-ipc-protocol JSON-RPC framing.

Usage::

    amplifier-foundation-serve
"""

from __future__ import annotations

from amplifier_ipc.protocol import Server


def main() -> None:
    """Start the amplifier-foundation IPC service."""
    Server("amplifier_foundation").run()


if __name__ == "__main__":
    main()
