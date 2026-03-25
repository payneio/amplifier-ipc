"""Amplifier Modes IPC tool — agent-initiated mode management."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from amplifier_ipc.protocol import ToolResult, tool

from amplifier_modes.hooks.mode import ModeDefinition, ModeHooks, parse_mode_file

logger = logging.getLogger(__name__)


@tool
class ModeTool:
    """Tool for agent-initiated mode management.

    Operations:
        list    - List all available modes (stub: returns empty)
        current - Show the currently active mode
        set     - Activate a mode (stub: not implemented)
        clear   - Deactivate the currently active mode
    """

    name = "mode"
    description = (
        "Manage runtime modes. Operations: 'set' (activate a mode), "
        "'clear' (deactivate), 'list' (show available), 'current' (show active). "
        "Mode transitions may require confirmation depending on gate policy."
    )

    input_schema: dict = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["set", "clear", "list", "current"],
                "description": "Operation to perform",
            },
            "name": {
                "type": "string",
                "description": "Mode name (required for 'set' operation)",
            },
        },
        "required": ["operation"],
    }

    _mode_hooks: Optional[ModeHooks] = None

    def _not_ready_result(self) -> ToolResult:
        return ToolResult(
            success=False,
            error={"code": "not_ready", "message": "Mode service not ready"},
        )

    def _discover_modes(self) -> list[ModeDefinition]:
        modes_by_name: dict[str, ModeDefinition] = {}
        # User-level first so project-level overwrites on collision
        for base in [Path.home(), Path.cwd()]:
            mode_dir = base / ".amplifier" / "modes"
            if not mode_dir.is_dir():
                continue
            for file_path in sorted(mode_dir.glob("*.md")):
                mode = parse_mode_file(file_path)
                if mode is not None:
                    mode.source = str(file_path)
                    modes_by_name[mode.name] = mode
        return list(modes_by_name.values())

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute a mode operation."""
        operation = input.get("operation", "")

        if operation == "list":
            return await self._handle_list()
        elif operation == "current":
            return await self._handle_current()
        elif operation == "set":
            return await self._handle_set(input)
        elif operation == "clear":
            return await self._handle_clear()
        else:
            return ToolResult(
                success=False,
                error={
                    "code": "invalid_operation",
                    "message": f"Unknown operation '{operation}'. Use: set, clear, list, current",
                },
            )

    async def _handle_list(self) -> ToolResult:
        """List available modes — stub returns empty."""
        return ToolResult(
            success=True,
            output={"modes": []},
        )

    async def _handle_current(self) -> ToolResult:
        """Show the currently active mode."""
        if self._mode_hooks is None:
            return self._not_ready_result()
        mode = self._mode_hooks.get_active_mode()
        if mode is None:
            return ToolResult(
                success=True,
                output={"active_mode": None, "message": "No mode is currently active."},
            )
        return ToolResult(
            success=True,
            output={"active_mode": mode.name, "description": mode.description},
        )

    async def _handle_set(self, input: dict[str, Any]) -> ToolResult:
        """Activate a mode — stub raises NotImplementedError."""
        raise NotImplementedError("ModeTool.set is not yet implemented")

    async def _handle_clear(self) -> ToolResult:
        """Deactivate the current mode."""
        if self._mode_hooks is None:
            return self._not_ready_result()
        self._mode_hooks.clear_active_mode()
        return ToolResult(
            success=True, output={"status": "cleared", "message": "Mode deactivated."}
        )
