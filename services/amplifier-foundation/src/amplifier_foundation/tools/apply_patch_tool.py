"""ApplyPatchTool stub — apply_patch file operations not yet implemented in IPC service."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import ToolResult, tool


@tool
class ApplyPatchTool:
    """Apply pre-parsed file operations (create, update, delete) from the Responses API (stub)."""

    name = "apply_patch"
    description = (
        "Apply pre-parsed file operations from the Responses API. "
        "Each call handles one operation: create_file, update_file, or delete_file."
    )

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["create_file", "update_file", "delete_file"],
                "description": "The operation type",
            },
            "path": {
                "type": "string",
                "description": "Relative file path",
            },
            "diff": {
                "type": "string",
                "description": "The diff content (not needed for delete_file)",
            },
        },
        "required": ["type", "path"],
    }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Return stub error — apply_patch file operations not yet implemented."""
        return ToolResult(
            success=False,
            error={
                "message": "ApplyPatchTool stub: apply_patch file operations not yet implemented in IPC service"
            },
        )
