"""Amplifier Modes IPC hook — runtime mode management."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from amplifier_ipc.protocol import HookAction, HookResult, hook

logger = logging.getLogger(__name__)


@dataclass
class ModeDefinition:
    """Parsed mode definition from a mode file."""

    name: str
    description: str = ""
    source: str = ""
    shortcut: str | None = None
    context: str = ""  # Markdown body - injected when mode active
    safe_tools: list[str] = field(default_factory=list)
    warn_tools: list[str] = field(default_factory=list)
    confirm_tools: list[str] = field(default_factory=list)  # Require user approval
    block_tools: list[str] = field(default_factory=list)
    default_action: str = "block"  # "block" or "allow"
    allowed_transitions: list[str] | None = None  # None = any transition allowed
    allow_clear: bool = True  # False = mode(clear) denied


def parse_mode_file(file_path: Path) -> ModeDefinition | None:
    """Parse a mode definition from a markdown file with YAML frontmatter.

    Expected format:
    ---
    mode:
      name: plan
      description: Think and discuss
      shortcut: plan
      tools:
        safe: [read_file, grep]
        warn: [bash]
      default_action: block
    ---

    # Mode Context

    This markdown content is injected when the mode is active...
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to read mode file {file_path}: {e}")
        return None

    # Parse YAML frontmatter
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not frontmatter_match:
        logger.warning(f"Mode file {file_path} missing YAML frontmatter")
        return None

    yaml_content = frontmatter_match.group(1)
    markdown_body = frontmatter_match.group(2).strip()

    try:
        parsed = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        logger.warning(f"Invalid YAML in mode file {file_path}: {e}")
        return None

    if not parsed or "mode" not in parsed:
        logger.warning(f"Mode file {file_path} missing 'mode:' section")
        return None

    mode_config = parsed["mode"]
    tools_config = mode_config.get("tools", {})

    return ModeDefinition(
        name=mode_config.get("name", file_path.stem),
        description=mode_config.get("description", ""),
        shortcut=mode_config.get("shortcut"),
        context=markdown_body,
        safe_tools=tools_config.get("safe", []),
        warn_tools=tools_config.get("warn", []),
        confirm_tools=tools_config.get("confirm", []),
        block_tools=tools_config.get("block", []),
        default_action=mode_config.get("default_action", "block"),
        allowed_transitions=mode_config.get("allowed_transitions"),
        allow_clear=mode_config.get("allow_clear", True),
    )


@hook(events=["provider:request", "tool:pre"], priority=5)
class ModeHooks:
    """Generic mode enforcement via hooks."""

    name = "mode_hooks"

    def __init__(self) -> None:
        self._warned_tools: set[str] = set()
        self._active_mode: ModeDefinition | None = None

    def set_active_mode(self, mode: ModeDefinition) -> None:
        """Set the active mode and reset warned-tools tracking."""
        self._active_mode = mode
        self._warned_tools.clear()

    def clear_active_mode(self) -> None:
        """Clear the active mode and reset warned-tools tracking."""
        self._active_mode = None
        self._warned_tools.clear()

    def get_active_mode(self) -> ModeDefinition | None:
        """Return the currently active mode, or None if no mode is active."""
        return self._active_mode

    async def handle(self, event: str, data: dict) -> HookResult:
        """Dispatch to the appropriate handler based on event type."""
        if event == "provider:request":
            return await self._handle_provider_request(event, data)
        elif event == "tool:pre":
            return await self._handle_tool_pre(event, data)
        return HookResult(action=HookAction.CONTINUE)

    async def _handle_provider_request(self, _event: str, _data: dict) -> HookResult:
        """Inject mode context on every provider request."""
        mode = self._active_mode
        if not mode or not mode.context:
            return HookResult(action=HookAction.CONTINUE)

        # Use mode context directly (no @-mention resolution in IPC)
        resolved_context = mode.context

        # Wrap context in system-reminder tags with explicit MODE ACTIVE banner
        context_block = (
            f'<system-reminder source="mode-{mode.name}">\n'
            f"MODE ACTIVE: {mode.name}\n"
            f"You are CURRENTLY in {mode.name} mode. It is already active — "
            f'do NOT call mode(set, "{mode.name}") to re-activate it. '
            f"Follow the guidance below.\n\n"
            f"{resolved_context}\n"
            f"</system-reminder>"
        )

        return HookResult(
            action=HookAction.INJECT_CONTEXT,
            context_injection=context_block,
            context_injection_role="system",
            ephemeral=True,
        )

    async def _handle_tool_pre(self, _event: str, data: dict) -> HookResult:
        """Moderate tools based on active mode policy."""
        mode = self._active_mode
        if not mode:
            return HookResult(action=HookAction.CONTINUE)

        tool_name = data.get("tool_name", "")

        # Safe tools: always allow
        if tool_name in mode.safe_tools:
            return HookResult(action=HookAction.CONTINUE)

        # Explicitly blocked tools: always deny
        if tool_name in mode.block_tools:
            return HookResult(
                action=HookAction.DENY,
                reason=f"Mode '{mode.name}': '{tool_name}' is blocked. {mode.description}",
            )

        # Warn-first tools: warn once, then allow
        if tool_name in mode.warn_tools:
            warn_key = f"{mode.name}:{tool_name}"
            if warn_key not in self._warned_tools:
                self._warned_tools.add(warn_key)
                return HookResult(
                    action=HookAction.DENY,
                    reason=f"Mode '{mode.name}': '{tool_name}' requires confirmation. "
                    f"Call again if this is appropriate for {mode.name} mode.",
                )
            return HookResult(action=HookAction.CONTINUE)

        # Default action for unlisted tools
        if mode.default_action == "allow":
            return HookResult(action=HookAction.CONTINUE)

        # Default is block
        return HookResult(
            action=HookAction.DENY,
            reason=f"Mode '{mode.name}': '{tool_name}' is not in the allowed list. "
            f"Use /mode off to exit {mode.name} mode.",
        )


# Exports for external use
__all__ = [
    "ModeDefinition",
    "ModeHooks",
    "parse_mode_file",
]
