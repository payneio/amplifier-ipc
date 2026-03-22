"""Routing hook proxy — resolves model roles against routing matrices."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from amplifier_ipc.protocol import hook
from amplifier_ipc.protocol.models import HookAction, HookResult

from .routing.matrix_loader import load_matrix

logger = logging.getLogger(__name__)


@hook(events=["session:start", "provider:request"], priority=5)
class RoutingHook:
    """Resolves model roles against routing matrices.

    Loads the default (balanced) matrix at startup, composes with any
    configured overrides, and injects available role info before each
    LLM request.
    """

    name = "routing"
    events = ["session:start", "provider:request"]
    priority = 5

    def __init__(self) -> None:
        self.base_matrix: dict[str, Any] = {}
        self.effective_matrix: dict[str, Any] = {}

        # Try to load the default balanced matrix
        # Look for routing directory relative to this package
        module_file = Path(__file__)
        package_root = module_file.parent.parent  # amplifier_foundation/
        routing_dir = package_root / "routing"

        matrix_path = routing_dir / "balanced.yaml"

        # Fall back to user's custom routing directory
        if not matrix_path.exists():
            custom_routing_dir = Path.home() / ".amplifier" / "routing"
            custom_matrix_path = custom_routing_dir / "balanced.yaml"
            if custom_matrix_path.exists():
                matrix_path = custom_matrix_path

        if matrix_path.exists():
            try:
                self.base_matrix = load_matrix(matrix_path)
                self.effective_matrix = self.base_matrix.get("roles", {})
            except Exception as e:
                logger.warning("Failed to load routing matrix: %s", e)
        else:
            logger.debug(
                "Routing matrix not found at %s — routing disabled", matrix_path
            )

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch to the appropriate handler based on event."""
        if event == "session:start":
            return await self._on_session_start(event, data)
        if event == "provider:request":
            return await self._on_provider_request(event, data)
        return HookResult(action=HookAction.CONTINUE)

    async def _on_session_start(self, _event: str, _data: dict[str, Any]) -> HookResult:
        """Resolve model roles at session start — stub for IPC mode."""
        # Full implementation requires session provider access
        # which is not available in standalone IPC hook mode
        return HookResult(action=HookAction.CONTINUE)

    async def _on_provider_request(
        self, _event: str, _data: dict[str, Any]
    ) -> HookResult:
        """Inject available model roles into context before each LLM call."""
        if not self.effective_matrix:
            return HookResult(action=HookAction.CONTINUE)

        lines = ["Active routing matrix: " + self.base_matrix.get("name", "balanced")]
        lines.append(
            "Available model roles (use model_role parameter when delegating):"
        )
        for role_name, role_data in self.effective_matrix.items():
            desc = (
                role_data.get("description", "") if isinstance(role_data, dict) else ""
            )
            lines.append(f"  {role_name:16s} — {desc}")

        return HookResult(
            action=HookAction.INJECT_CONTEXT,
            context_injection="\n".join(lines),
            ephemeral=True,
        )
