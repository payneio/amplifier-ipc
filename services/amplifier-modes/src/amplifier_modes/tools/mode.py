"""Amplifier Modes IPC tool — agent-initiated mode management."""

from __future__ import annotations

import logging
from typing import Any

from amplifier_ipc.protocol import ToolResult, tool

logger = logging.getLogger(__name__)


@tool
class ModeTool:
    """Tool for agent-initiated mode management.

    Operations:
        list    - List all available modes (stub: returns empty)
        current - Show the currently active mode (stub: returns no active mode)
        set     - Activate a mode (stub: not implemented)
        clear   - Deactivate the current mode (stub: returns success)
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
        """Show the currently active mode — stub returns no active mode."""
        return ToolResult(
            success=True,
            output={
                "active_mode": None,
                "message": "No mode is currently active.",
            },
        )

    async def _handle_set(self, input: dict[str, Any]) -> ToolResult:
        """Activate a mode — stub raises NotImplementedError."""
        raise NotImplementedError("ModeTool.set is not yet implemented")

    async def _handle_clear(self) -> ToolResult:
        """Deactivate the current mode — stub returns simple success."""
        return ToolResult(
            success=True,
            output={
                "status": "cleared",
                "message": "Mode deactivated.",
            },
        )
