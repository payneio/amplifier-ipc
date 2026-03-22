"""ShadowTool stub — shadow environment management not yet implemented in IPC service."""

from __future__ import annotations

from typing import Any

from amplifier_ipc.protocol import ToolResult, tool


@tool
class ShadowTool:
    """Manage shadow (isolated) environments for safe testing and development (stub)."""

    name = "shadow"
    description = (
        "Manage shadow (isolated) environments for safe testing and development. "
        "Supports creating, listing, destroying, and executing commands in shadow environments."
    )

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["create", "list", "destroy", "exec", "snapshot"],
                "description": "Operation to perform on shadow environments",
            },
            "name": {
                "type": "string",
                "description": "Name of the shadow environment",
            },
            "image": {
                "type": "string",
                "description": "Container image to use when creating the environment",
            },
            "local_sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Local source paths to mount into the environment",
            },
            "command": {
                "type": "string",
                "description": "Command to execute inside the shadow environment",
            },
            "env": {
                "type": "object",
                "description": "Environment variables to set in the shadow environment",
            },
        },
        "required": ["operation"],
    }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Return stub error — shadow environment management not yet implemented."""
        return ToolResult(
            success=False,
            error={
                "message": "ShadowTool stub: shadow environment management not yet implemented in IPC service"
            },
        )
