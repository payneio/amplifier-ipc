"""RoutingHook — model routing based on curated role-to-provider matrices.

Ported from amplifier-lite class-based Hook to amplifier-ipc-protocol
hook with @hook decorator and unified handle() method.

Registers two events:
- session:start (priority 5): resolve model_role for all agents (stub in IPC mode)
- provider:request (priority 5): inject available roles into context
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from amplifier_ipc_protocol import HookAction, HookResult, hook

from .matrix_loader import compose_matrix, load_matrix

logger = logging.getLogger(__name__)


@hook(events=["session:start", "provider:request"], priority=5)
class RoutingHook:
    """Hook that resolves model roles against routing matrices.

    Loads a default matrix, composes with config/capability overrides,
    and registers handlers for session:start and provider:request events.
    """

    name = "routing_hook"

    def __init__(self) -> None:
        # Locate routing directory relative to package root
        module_file = Path(__file__)
        package_root = module_file.parent.parent
        routing_dir = package_root / "routing"

        # Load default matrix
        default_matrix_name = "balanced"
        matrix_path = routing_dir / f"{default_matrix_name}.yaml"

        if not matrix_path.exists():
            custom_routing_dir = Path.home() / ".amplifier" / "routing"
            custom_matrix_path = custom_routing_dir / f"{default_matrix_name}.yaml"
            if custom_matrix_path.exists():
                matrix_path = custom_matrix_path

        self.base_matrix: dict[str, Any] = {}
        if matrix_path.exists():
            self.base_matrix = load_matrix(matrix_path)
        else:
            logger.warning("Matrix file not found: %s — routing disabled", matrix_path)

        self.effective_matrix: dict[str, Any] = {}
        if self.base_matrix:
            self.effective_matrix = compose_matrix(
                self.base_matrix.get("roles", {}), {}
            )

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch incoming events to the appropriate handler."""
        if event == "session:start":
            return await self._on_session_start(event, data)
        elif event == "provider:request":
            return await self._on_provider_request(event, data)
        return HookResult(action=HookAction.CONTINUE)

    async def _on_session_start(self, event: str, data: dict[str, Any]) -> HookResult:
        """Resolve model roles at session start (stub — requires host provider access)."""
        return HookResult(action=HookAction.CONTINUE)

    async def _on_provider_request(self, event: str, data: dict[str, Any]) -> HookResult:
        """Inject available model roles into context before each LLM call."""
        if not self.effective_matrix:
            return HookResult(action=HookAction.CONTINUE)

        lines = [
            "Active routing matrix: " + self.base_matrix.get("name", "unknown")
        ]
        lines.append(
            "Available model roles (use model_role parameter when delegating):"
        )
        for role_name, role_data in self.effective_matrix.items():
            desc = (
                role_data.get("description", "") if isinstance(role_data, dict) else ""
            )
            lines.append(f"  {role_name:16s} — {desc}")

        return HookResult(
            action=HookAction.MODIFY,
            data={"routing_context": "\n".join(lines)},
        )
