"""MCPToolWrapper stub — MCP server integration not yet implemented in IPC service."""

from __future__ import annotations

from typing import Any

from amplifier_ipc.protocol import ToolResult, tool


@tool
class MCPToolWrapper:
    """Interact with MCP (Model Context Protocol) servers (stub)."""

    name = "mcp"
    description = (
        "Interact with external MCP (Model Context Protocol) servers. "
        "Allows calling tools exposed by connected MCP servers."
    )

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "server": {
                "type": "string",
                "description": "Name of the MCP server to interact with",
            },
            "tool_name": {
                "type": "string",
                "description": "Name of the tool on the MCP server to invoke",
            },
            "arguments": {
                "type": "object",
                "description": "Arguments to pass to the MCP tool",
            },
        },
        "required": ["server", "tool_name"],
    }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Return stub error — MCP server integration not yet implemented."""
        return ToolResult(
            success=False,
            error={
                "message": "MCPToolWrapper stub: MCP server integration not yet implemented in IPC service"
            },
        )
