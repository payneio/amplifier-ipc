"""DelegateTool — spawns or resumes a child session via the host's session_spawn IPC."""

from __future__ import annotations

from typing import Any

from amplifier_ipc.protocol import ToolResult, tool
from amplifier_ipc_protocol.events import (
    DELEGATE_AGENT_COMPLETED,
    DELEGATE_AGENT_RESUMED,
    DELEGATE_AGENT_SPAWNED,
    DELEGATE_ERROR,
)


@tool
class DelegateTool:
    """Spawn a specialized agent to handle tasks autonomously."""

    name = "delegate"
    description = "Spawn a specialized agent to handle tasks autonomously."

    # Injected by the protocol server's _handle_tool_execute when the
    # orchestrator is active (allows IPC calls back to the host).
    client: Any = None

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "description": (
                    "Agent to delegate to (e.g., 'foundation:explorer', 'self', "
                    "or bundle path). Defaults to 'self'."
                ),
            },
            "instruction": {
                "type": "string",
                "description": "Clear instruction for the agent",
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Resume an existing session by ID instead of spawning a new one."
                ),
            },
            "context_depth": {
                "type": "string",
                "enum": ["none", "recent", "all"],
                "description": "How much parent context to pass to the child session.",
            },
            "context_scope": {
                "type": "string",
                "enum": ["conversation", "all"],
                "description": "Which messages to include in parent context.",
            },
            "context_turns": {
                "type": "integer",
                "description": "Number of recent turns to include (when context_depth='recent').",
            },
            "exclude_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool names to remove from the child session (blocklist).",
            },
            "inherit_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool names to keep in the child session (allowlist).",
            },
            "model_role": {
                "type": "string",
                "description": "Override the child agent's default model role.",
            },
        },
        "required": ["instruction"],
    }

    async def _emit_hook(self, event: str, data: dict[str, Any]) -> None:
        """Fire-and-forget hook emission — silently ignores errors."""
        if self.client is not None:
            try:
                await self.client.request(
                    "request.hook_emit", {"event": event, "data": data}
                )
            except Exception:  # noqa: BLE001
                pass

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Spawn or resume a child session via request.session_spawn / request.session_resume."""
        agent_name: str = input.get("agent", "self")
        instruction: str = input.get("instruction", "")
        session_id: str | None = input.get("session_id")

        try:
            if session_id:
                # Resume an existing session
                await self._emit_hook(
                    DELEGATE_AGENT_RESUMED, {"session_id": session_id}
                )
                params: dict[str, Any] = {
                    "session_id": session_id,
                    "instruction": instruction,
                }
                result = await self.client.request("request.session_resume", params)
            else:
                # Spawn a new child session
                await self._emit_hook(
                    DELEGATE_AGENT_SPAWNED,
                    {
                        "agent": agent_name,
                        "context_depth": input.get("context_depth"),
                        "context_scope": input.get("context_scope"),
                    },
                )
                params = {
                    "agent": agent_name,
                    "instruction": instruction,
                }
                # Forward optional spawning parameters if provided
                for key in (
                    "context_depth",
                    "context_scope",
                    "context_turns",
                    "exclude_tools",
                    "inherit_tools",
                    "model_role",
                ):
                    if key in input:
                        params[key] = input[key]
                result = await self.client.request("request.session_spawn", params)

            child_session_id: str = result.get("session_id", "")
            response: str = result.get("response", "")
            turn_count: int = result.get("turn_count", 0)

            await self._emit_hook(
                DELEGATE_AGENT_COMPLETED,
                {
                    "agent": agent_name,
                    "sub_session_id": child_session_id,
                    "success": True,
                    "turn_count": turn_count,
                },
            )

            output = f"[Delegate session: {child_session_id}]\n[Turns: {turn_count}]\n\n{response}"
            return ToolResult(success=True, output=output)

        except Exception as exc:  # noqa: BLE001
            await self._emit_hook(
                DELEGATE_ERROR, {"agent": agent_name, "error": str(exc)}
            )
            return ToolResult(
                success=False,
                error={"message": str(exc)},
            )
