"""Todo display hook — renders visual todo progress after todo tool calls."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import hook
from amplifier_ipc_protocol.models import HookAction, HookResult


@hook(events=["tool:pre", "tool:post"], priority=50)
class TodoDisplayHook:
    """Renders a visual todo progress display after todo tool calls.

    Note: Stubbed — returns CONTINUE until shared state mechanism is available.
    """

    name = "todo_display"
    events = ["tool:pre", "tool:post"]
    priority = 50

    def __init__(self) -> None:
        pass  # No state needed while stubbed

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch to the appropriate handler based on event."""
        if event == "tool:pre":
            return await self._handle_tool_pre(event, data)
        if event == "tool:post":
            return await self._handle_tool_post(event, data)
        return HookResult(action=HookAction.CONTINUE)

    async def _handle_tool_pre(self, _event: str, _data: dict[str, Any]) -> HookResult:
        """Capture todo data before tool execution for display after.

        # TODO: implement when shared state is available
        """
        return HookResult(action=HookAction.CONTINUE)

    async def _handle_tool_post(self, _event: str, _data: dict[str, Any]) -> HookResult:
        """Render todo progress display after tool execution.

        # TODO: implement when shared state is available
        """
        return HookResult(action=HookAction.CONTINUE)
