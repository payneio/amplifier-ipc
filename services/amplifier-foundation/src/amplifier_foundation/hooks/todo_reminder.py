"""Todo reminder hook — injects todo list reminders before each LLM request."""

from __future__ import annotations

import logging
from typing import Any

from amplifier_ipc.protocol import hook
from amplifier_ipc.protocol.models import HookAction, HookResult

logger = logging.getLogger(__name__)


@hook(events=["tool:post", "provider:request"], priority=10)
class TodoReminderHook:
    """Injects current todo list reminders before each LLM request.

    Note: Session state access (todo_state) is stubbed out — returns CONTINUE
    for now until a shared state mechanism is available.
    """

    name = "todo_reminder"
    events = ["tool:post", "provider:request"]
    priority = 10

    def __init__(self) -> None:
        self.inject_role = "user"
        self.recent_tool_threshold = 3

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch to the appropriate handler based on event.

        Both tool:post and provider:request are stubbed out to return CONTINUE
        until a shared state mechanism for todo_state is available.
        """
        # Stub: shared state (session.todo_state) not yet available in IPC pattern.
        # Returns CONTINUE so hook is safely registered but not yet functional.
        return HookResult(action=HookAction.CONTINUE)
