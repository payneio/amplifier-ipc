"""Approval hook proxy — discovered by scan_package, delegates to approval/ package."""

from __future__ import annotations

import logging
from typing import Any

from amplifier_ipc_protocol import hook
from amplifier_ipc_protocol.models import HookAction, HookResult

from .approval.approval_hook import _ApprovalCore

logger = logging.getLogger(__name__)


@hook(events=["tool:pre"], priority=5)
class ApprovalHook:
    """Proxy hook — intercepts tool:pre events and applies approval logic.

    Delegates to approval._ApprovalCore for the actual decision logic.
    In IPC mode, interactive approval is not available, so tools are
    auto-approved (with audit logging) unless an auto-deny rule matches.
    """

    name = "approval"
    events = ["tool:pre"]
    priority = 5

    def __init__(self) -> None:
        self._core = _ApprovalCore(config={})

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch to the appropriate handler based on event."""
        if event == "tool:pre":
            return await self._core._handle_tool_pre(event, data)
        return HookResult(action=HookAction.CONTINUE)
