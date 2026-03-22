"""TaskTool — spawns a self-session for complex, multi-step tasks via IPC."""

from __future__ import annotations

from typing import Any

from amplifier_ipc.protocol import ToolResult, tool


@tool
class TaskTool:
    """Launch a new agent to handle complex, multi-step tasks autonomously."""

    name = "task"
    description = "Launch a new agent to handle complex, multi-step tasks autonomously."

    # Injected by the protocol server's _handle_tool_execute when the
    # orchestrator is active (allows IPC calls back to the host).
    client: Any = None

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
        """Spawn a self-clone session to execute the task autonomously."""
        try:
            instruction: str = input["task"]

            params: dict[str, Any] = {
                "agent": "self",
                "instruction": instruction,
                "context_depth": "none",
                "context_scope": "conversation",
            }

            result = await self.client.request("request.session_spawn", params)

            session_id: str = result.get("session_id", "")
            response: str = result.get("response", "")
            turn_count: int = result.get("turn_count", 0)

            output = (
                f"[Task session: {session_id}]\n[Turns: {turn_count}]\n\n{response}"
            )
            return ToolResult(success=True, output=output)

        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                error={"message": str(exc)},
            )
