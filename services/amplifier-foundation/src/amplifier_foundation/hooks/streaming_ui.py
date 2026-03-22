"""Streaming UI hook — displays tool calls and thinking blocks in the terminal.

Note: Actual rendering is stubbed — rich.console output won't work over IPC.
The hook is safely registered with a handle() dispatcher, but visual output
is skipped to avoid corrupting IPC framing with ANSI escape sequences.
"""

from __future__ import annotations

import logging
from typing import Any

from amplifier_ipc.protocol import hook
from amplifier_ipc.protocol.models import HookAction, HookResult

logger = logging.getLogger(__name__)

_STREAMING_UI_EVENTS = [
    "tool:pre",
    "tool:post",
    "content_block:start",
    "content_block:end",
    "provider:response",
]


@hook(events=_STREAMING_UI_EVENTS, priority=50)
class StreamingUIHook:
    """Displays streaming UI output (tool calls, thinking blocks, token usage).

    Note: Actual rendering (rich.console, ANSI escapes) is stubbed in IPC
    mode — visual output over a JSON-RPC channel would corrupt framing.
    Returns CONTINUE so the hook is safely registered but not yet functional.
    """

    name = "streaming_ui"
    events = _STREAMING_UI_EVENTS
    priority = 50

    def __init__(self) -> None:
        # Config placeholders — used when rendering is un-stubbed
        self.show_thinking = True
        self.show_tool_lines = 10
        self.show_token_usage = True

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch to the appropriate handler based on event.

        All handlers are stubbed — rendering won't work over IPC.
        """
        if event == "tool:pre":
            return await self._handle_tool_pre(event, data)
        if event == "tool:post":
            return await self._handle_tool_post(event, data)
        if event == "content_block:start":
            return await self._handle_content_block_start(event, data)
        if event == "content_block:end":
            return await self._handle_content_block_end(event, data)
        if event == "provider:response":
            return await self._handle_provider_response(event, data)
        return HookResult(action=HookAction.CONTINUE)

    async def _handle_tool_pre(self, _event: str, _data: dict[str, Any]) -> HookResult:
        """Display tool invocation — stubbed in IPC mode."""
        # Stub: ANSI/rich output not supported over IPC channel
        return HookResult(action=HookAction.CONTINUE)

    async def _handle_tool_post(self, _event: str, _data: dict[str, Any]) -> HookResult:
        """Display tool result — stubbed in IPC mode."""
        return HookResult(action=HookAction.CONTINUE)

    async def _handle_content_block_start(
        self, _event: str, _data: dict[str, Any]
    ) -> HookResult:
        """Detect thinking blocks — stubbed in IPC mode."""
        return HookResult(action=HookAction.CONTINUE)

    async def _handle_content_block_end(
        self, _event: str, _data: dict[str, Any]
    ) -> HookResult:
        """Display complete thinking block and token usage — stubbed in IPC mode."""
        return HookResult(action=HookAction.CONTINUE)

    async def _handle_provider_response(
        self, _event: str, _data: dict[str, Any]
    ) -> HookResult:
        """Capture model/provider info — stubbed in IPC mode."""
        return HookResult(action=HookAction.CONTINUE)
