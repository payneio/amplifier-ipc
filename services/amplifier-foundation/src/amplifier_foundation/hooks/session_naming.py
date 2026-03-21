"""Session naming hook — automatically generates names for sessions.

Note: Stubbed — returns CONTINUE until provider/session access is available
in IPC mode. The full implementation requires LLM calls via a provider.
"""

from __future__ import annotations

import logging
from typing import Any

from amplifier_ipc_protocol import hook
from amplifier_ipc_protocol.models import HookAction, HookResult

logger = logging.getLogger(__name__)


@hook(events=["prompt:complete"], priority=90)
class SessionNamingHook:
    """Automatically generates session names by calling the LLM provider.

    Note: Stubbed in IPC mode — returns CONTINUE until provider access is
    available. The full implementation makes LLM calls to generate a short
    descriptive name for the session.
    """

    name = "session_naming"
    events = ["prompt:complete"]
    priority = 90

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch to the appropriate handler based on event.

        Stub: provider access (for LLM calls) is not yet available in IPC
        mode. Returns CONTINUE so the hook is safely registered.
        """
        # Stub: LLM provider calls not yet available in IPC pattern.
        # Returns CONTINUE so hook is safely registered but not yet functional.
        return HookResult(action=HookAction.CONTINUE)
