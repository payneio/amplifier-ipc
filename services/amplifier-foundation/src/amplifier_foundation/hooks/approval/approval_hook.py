"""Core approval hook logic — ported for IPC mode.

Key changes from original:
- Removed amplifier_lite.hooks.HookRegistry dependency
- Removed amplifier_lite.session.Session dependency
- Removed internal emit calls (APPROVAL_REQUIRED/GRANTED/DENIED); just log
- ApprovalProvider is auto-approve in IPC mode (no interactive provider)
- Renamed handle_tool_pre → _handle_tool_pre (internal)
- Added handle() dispatcher for IPC discovery
"""

from __future__ import annotations

import logging
from typing import Any

from amplifier_ipc.protocol.models import HookAction, HookResult
from amplifier_ipc_protocol.events import APPROVAL_DENIED, APPROVAL_GRANTED, APPROVAL_REQUIRED

from .audit import ApprovalRequest, ApprovalResponse, audit_log
from .config import DEFAULT_RULES, check_auto_action

logger = logging.getLogger(__name__)


class _ApprovalCore:
    """Core approval logic, decoupled from IPC hook infrastructure."""

    client: Any = None

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.rules = config.get("rules", DEFAULT_RULES)
        self.default_action = config.get("default_action", "deny")
        self.audit_enabled = config.get("audit", {}).get("enabled", True)
        self.policy_driven_only = config.get("policy_driven_only", False)
        logger.debug("_ApprovalCore initialized with %d rules", len(self.rules))

    async def _emit_hook(self, event: str, data: dict[str, Any]) -> None:
        """Emit a hook event via the injected IPC client.

        No-ops when client is None. Swallows exceptions to avoid disrupting
        the main approval flow.
        """
        if self.client is None:
            return
        try:
            await self.client.request(
                "request.hook_emit", {"event": event, "data": data}
            )
        except Exception:
            pass

    async def _handle_tool_pre(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle tool:pre event and request approval if needed."""
        tool_name = data.get("tool_name", "unknown")
        tool_input = data.get("tool_input", {})

        if not self._needs_approval(tool_name, tool_input):
            return HookResult(action=HookAction.CONTINUE)

        request = self._build_request(tool_name, tool_input)

        # Log approval required and emit event
        logger.info(
            "approval:required tool=%s action=%s risk=%s",
            tool_name,
            request.action,
            request.risk_level,
        )
        await self._emit_hook(
            APPROVAL_REQUIRED,
            {
                "tool_name": tool_name,
                "action": request.action,
                "risk_level": request.risk_level,
                "tool_input": tool_input,
                "timeout": request.timeout,
            },
        )

        # Check for auto-action rules first
        auto_action = check_auto_action(self.rules, tool_name, tool_input)
        if auto_action:
            logger.info("Auto-action '%s' for %s", auto_action, tool_name)

            if self.audit_enabled:
                response = ApprovalResponse(
                    approved=(auto_action == "auto_approve"),
                    reason=f"Auto-action: {auto_action}",
                )
                audit_log(request, response)

            if auto_action == "auto_approve":
                logger.info(
                    "approval:granted tool=%s reason=Auto-approved by rule", tool_name
                )
                await self._emit_hook(
                    APPROVAL_GRANTED,
                    {"tool_name": tool_name, "reason": "Auto-approved by rule"},
                )
                return HookResult(action=HookAction.CONTINUE)

            logger.info("approval:denied tool=%s reason=Auto-denied by rule", tool_name)
            await self._emit_hook(
                APPROVAL_DENIED,
                {"tool_name": tool_name, "reason": "Auto-denied by rule"},
            )
            return HookResult(action=HookAction.DENY, reason="Auto-denied by rule")

        # In IPC mode: auto-approve (no interactive provider available)
        logger.info(
            "approval:granted tool=%s reason=Auto-approved in IPC mode (no interactive provider)",
            tool_name,
        )
        if self.audit_enabled:
            response = ApprovalResponse(
                approved=True,
                reason="Auto-approved in IPC mode",
            )
            audit_log(request, response)

        await self._emit_hook(
            APPROVAL_GRANTED,
            {"tool_name": tool_name, "reason": "Auto-approved in IPC mode"},
        )

        return HookResult(action=HookAction.CONTINUE)

    def _needs_approval(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        """Check if tool execution needs approval."""
        if self.policy_driven_only:
            return False

        # Check config for tool-specific approval requirements
        tool_config = self.config.get("tools", {}).get(tool_name, {})
        if tool_config.get("require_approval", False):
            return True

        # Special handling for bash — always requires approval
        if tool_name == "bash":
            return True

        # Check if tool is in high-risk list
        high_risk_tools = ["write", "edit", "bash", "execute", "run"]
        return tool_name in high_risk_tools

    def _build_request(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> ApprovalRequest:
        """Build approval request from tool info."""
        if tool_name == "bash":
            action = f"Execute: {tool_input.get('command', 'unknown command')}"
        else:
            action = f"Execute {tool_name}"

        risk_level = "high" if tool_name == "bash" else "medium"

        return ApprovalRequest(
            tool_name=tool_name,
            action=action,
            details=tool_input,
            risk_level=risk_level,
            timeout=self.config.get("default_timeout"),
        )
