"""DelegateTool stub — sub-session spawning not yet implemented in IPC service."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import ToolResult, tool


@tool
class DelegateTool:
    """Spawn a specialized agent to handle tasks autonomously (stub)."""

    name = "delegate"
    description = "Spawn a specialized agent to handle tasks autonomously."

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "description": "Agent to delegate to (e.g., 'foundation:explorer', 'self', or bundle path)",
            },
            "instruction": {
                "type": "string",
                "description": "Clear instruction for the agent",
            },
        },
        "required": ["instruction"],
    }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Return stub error — sub-session spawning not yet implemented."""
        return ToolResult(
            success=False,
            error={
                "message": "DelegateTool stub: sub-session spawning not yet implemented in IPC service"
            },
        )
