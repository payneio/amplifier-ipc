"""TaskTool stub — sub-session spawning not yet implemented in IPC service."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import ToolResult, tool


@tool
class TaskTool:
    """Launch a specialized agent to handle complex, multi-step tasks (stub)."""

    name = "task"
    description = "Launch a new agent to handle complex, multi-step tasks autonomously."

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Task instruction for the agent",
            },
        },
        "required": ["task"],
    }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Return stub error — sub-session spawning not yet implemented."""
        return ToolResult(
            success=False,
            error={
                "message": "TaskTool stub: sub-session spawning not yet implemented in IPC service"
            },
        )
