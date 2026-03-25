"""Entry point for amplifier-modes IPC service."""

from __future__ import annotations

from amplifier_ipc.protocol import Server
from amplifier_modes.hooks.mode import ModeHooks
from amplifier_modes.tools.mode import ModeTool


class ModeServer(Server):
    """ModeServer wires ModeTool to ModeHooks at startup via _build_runtime_state()."""

    def _build_runtime_state(self) -> None:
        """Build runtime state and wire ModeTool to ModeHooks."""
        super()._build_runtime_state()

        mode_tool = self._tools.get("mode")
        mode_hook = next(
            (h for h in self._hook_instances if isinstance(h, ModeHooks)),
            None,
        )

        if isinstance(mode_tool, ModeTool) and mode_hook is not None:
            mode_tool._mode_hooks = mode_hook  # type: ignore[attr-defined]


def main() -> None:
    """Start the amplifier-modes IPC service."""
    ModeServer("amplifier_modes").run()


if __name__ == "__main__":
    main()
