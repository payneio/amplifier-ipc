"""PythonDevTool stub — Python code quality checks not yet implemented in IPC service."""

from __future__ import annotations

from typing import Any

from amplifier_ipc.protocol import ToolResult, tool


@tool
class PythonDevTool:
    """Check Python code for quality issues using ruff and pyright (stub)."""

    name = "python_check"
    description = (
        "Check Python code for quality issues. "
        "Runs ruff (formatting and linting), pyright (type checking), and stub detection "
        "on Python files or code content."
    )

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of file paths or directories to check",
            },
            "content": {
                "type": "string",
                "description": "Python code as a string to check (alternative to paths)",
            },
            "fix": {
                "type": "boolean",
                "default": False,
                "description": "Auto-fix issues where possible (only works with paths)",
            },
            "checks": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["format", "lint", "types", "stubs"],
                },
                "description": "Specific checks to run (default: all)",
            },
        },
    }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Return stub error — Python code quality checks not yet implemented."""
        return ToolResult(
            success=False,
            error={
                "message": "PythonDevTool stub: Python code quality checks not yet implemented in IPC service"
            },
        )
