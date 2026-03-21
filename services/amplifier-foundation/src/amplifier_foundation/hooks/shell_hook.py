"""Shell hook proxy — executes .amplifier/hooks/ shell scripts on events."""

from __future__ import annotations

import logging
from typing import Any

from amplifier_ipc_protocol import hook
from amplifier_ipc_protocol.models import HookResult

from .shell.bridge import ShellHookBridge

logger = logging.getLogger(__name__)

_SHELL_HOOK_EVENTS = [
    "tool:pre",
    "tool:post",
    "prompt:submit",
    "session:start",
    "session:end",
    "prompt:complete",
    "context:pre_compact",
    "approval:required",
    "session:resume",
    "user:notification",
]


@hook(events=_SHELL_HOOK_EVENTS, priority=50)
class ShellHook:
    """Proxy hook — executes user-defined shell scripts for events.

    Loads hook configurations from .amplifier/hooks/ in the project directory
    and delegates to ShellHookBridge for execution.
    """

    name = "shell"
    events = _SHELL_HOOK_EVENTS
    priority = 50

    def __init__(self) -> None:
        self._bridge = ShellHookBridge(config={})

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch to ShellHookBridge for execution."""
        return await self._bridge.handle(event, data)
