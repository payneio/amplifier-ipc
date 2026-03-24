"""RoutingHook — model routing based on curated role-to-provider matrices.

Registers two events:
- session:start (priority 5): log active matrix info
- provider:request (priority 5): resolve model_role to provider+model and inject
  into the request data so the orchestrator routes to the correct backend
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from amplifier_ipc.protocol import HookAction, HookResult, hook

from .matrix_loader import compose_matrix, load_matrix

logger = logging.getLogger(__name__)


@hook(events=["session:start", "provider:request"], priority=5)
class RoutingHook:
    """Hook that resolves model roles against routing matrices.

    Loads a default matrix (or a named one from config), composes with
    overrides, and resolves ``model_role`` in provider:request data to
    concrete provider+model pairs.
    """

    name = "routing_hook"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        default_matrix_name = config.get("default_matrix", "balanced")

        # Locate routing directory relative to package root
        module_file = Path(__file__)
        package_root = module_file.parent.parent
        routing_dir = package_root / "routing"

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
            user_overrides = config.get("overrides", {})
            self.effective_matrix = compose_matrix(
                self.base_matrix.get("roles", {}), user_overrides
            )

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch incoming events to the appropriate handler."""
        if event == "session:start":
            return await self._on_session_start(data)
        elif event == "provider:request":
            return await self._on_provider_request(data)
        return HookResult(action=HookAction.CONTINUE)

    async def _on_session_start(self, data: dict[str, Any]) -> HookResult:
        """Log active matrix info at session start."""
        matrix_name = self.base_matrix.get("name", "unknown")
        role_count = len(self.effective_matrix)
        logger.info("Routing matrix '%s' active with %d roles", matrix_name, role_count)
        return HookResult(action=HookAction.CONTINUE)

    async def _on_provider_request(self, data: dict[str, Any]) -> HookResult:
        """Resolve model_role to a concrete provider+model pair.

        If ``data`` contains a ``model_role`` key, looks it up in the
        effective matrix and injects the resolved ``provider`` and ``model``
        into the returned data.  The orchestrator can then use these to
        route the provider.complete call to the correct backend.

        Also injects ``routing_context`` with available roles for the LLM
        to use when delegating to sub-agents.
        """
        if not self.effective_matrix:
            return HookResult(action=HookAction.CONTINUE)

        modified_data = dict(data)

        # Resolve model_role if present
        model_role = data.get("model_role")
        if model_role:
            resolved = self._resolve_role(model_role)
            if resolved:
                modified_data["provider"] = resolved["provider"]
                modified_data["model"] = resolved["model"]
                if resolved.get("config"):
                    modified_data["provider_config"] = resolved["config"]
                logger.info(
                    "Resolved model_role '%s' → provider=%s, model=%s",
                    model_role,
                    resolved["provider"],
                    resolved["model"],
                )

        # Inject routing context for LLM awareness
        lines = ["Active routing matrix: " + self.base_matrix.get("name", "unknown")]
        lines.append(
            "Available model roles (use model_role parameter when delegating):"
        )
        for role_name, role_data in self.effective_matrix.items():
            desc = (
                role_data.get("description", "") if isinstance(role_data, dict) else ""
            )
            lines.append(f"  {role_name:16s} — {desc}")
        modified_data["routing_context"] = "\n".join(lines)

        return HookResult(
            action=HookAction.MODIFY,
            data=modified_data,
        )

    def _resolve_role(self, role: str) -> dict[str, Any] | None:
        """Resolve a role name to a provider+model+config dict.

        Tries roles in order: the requested role, then 'general' as fallback.
        For each role, iterates candidates and returns the first one
        (candidate priority ordering is handled by the matrix file).
        """
        roles_to_try = [role]
        if role != "general":
            roles_to_try.append("general")

        for role_name in roles_to_try:
            role_data = self.effective_matrix.get(role_name)
            if not isinstance(role_data, dict):
                continue

            candidates = role_data.get("candidates", [])
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                provider = candidate.get("provider")
                model = candidate.get("model")
                if provider and model:
                    return {
                        "provider": provider,
                        "model": model,
                        "config": candidate.get("config", {}),
                    }

        return None
