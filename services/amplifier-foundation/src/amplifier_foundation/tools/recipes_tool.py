"""RecipesTool stub — recipe execution not yet implemented in IPC service."""

from __future__ import annotations

from typing import Any

from amplifier_ipc.protocol import ToolResult, tool


@tool
class RecipesTool:
    """Execute multi-step AI agent recipes (workflows) (stub)."""

    name = "recipes"
    description = (
        "Execute multi-step AI agent recipes (workflows). "
        "Supports sequential execution, approval gates, checkpointing, and resumability."
    )

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "execute",
                    "resume",
                    "list",
                    "validate",
                    "approvals",
                    "approve",
                    "deny",
                    "cancel",
                ],
                "description": "Operation to perform",
            },
            "recipe_path": {
                "type": "string",
                "description": (
                    "Path to recipe YAML file. Supports @bundle:path format "
                    "(e.g., @recipes:examples/code-review.yaml). "
                    "Required for 'execute' and 'validate' operations."
                ),
            },
            "context": {
                "type": "object",
                "description": "Context variables for recipe execution (for 'execute' operation)",
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Session ID (required for 'resume', 'approve', 'deny', 'cancel' operations)"
                ),
            },
            "stage_name": {
                "type": "string",
                "description": (
                    "Stage name to approve or deny (required for 'approve' and 'deny' operations)"
                ),
            },
            "reason": {
                "type": "string",
                "description": "Reason for denial (optional for 'deny' operation)",
            },
            "message": {
                "type": "string",
                "description": (
                    "Optional message from the user when approving. "
                    "Made available to subsequent steps as {{_approval_message}}."
                ),
            },
            "immediate": {
                "type": "boolean",
                "description": (
                    "If true, request immediate cancellation (don't wait for current step). "
                    "For 'cancel' operation."
                ),
            },
        },
        "required": ["operation"],
    }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Return stub error — recipe execution not yet implemented."""
        return ToolResult(
            success=False,
            error={
                "message": "RecipesTool stub: recipe execution not yet implemented in IPC service"
            },
        )
