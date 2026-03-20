"""Amplifier Modes IPC hook — runtime mode management."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from amplifier_ipc_protocol import HookAction, HookResult, hook

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


class ModeDiscovery:
    """Discover mode definitions from search paths.

    Args:
        search_paths: Explicit paths to search for mode files
        working_dir: Project directory for `.amplifier/modes/` discovery.
            Falls back to cwd. Important for server deployments where
            process cwd differs from user's project directory.
    """

    def __init__(
        self,
        search_paths=None,
        working_dir=None,
    ):
        self._working_dir = working_dir or Path.cwd()
        # Normalize search_paths: accept bare Paths (legacy) or (Path, source) tuples
        if search_paths is not None:
            normalized: list[tuple[Path, str]] = []
            for entry in search_paths:
                if isinstance(entry, tuple):
                    normalized.append(entry)
                else:
                    normalized.append((entry, ""))
            self._search_paths = normalized
        else:
            self._search_paths = self._default_search_paths()
        self._cache: dict[str, ModeDefinition] = {}

    def _default_search_paths(self) -> list[tuple[Path, str]]:
        """Get default search paths for mode discovery."""
        paths: list[tuple[Path, str]] = []

        # Project modes (highest precedence) - use working_dir instead of cwd
        project_modes = self._working_dir / ".amplifier" / "modes"
        if project_modes.exists():
            paths.append((project_modes, "project"))

        # User modes
        user_modes = Path.home() / ".amplifier" / "modes"
        if user_modes.exists():
            paths.append((user_modes, "user"))

        return paths

    def add_search_path(self, path: Path, source: str = "") -> None:
        """Add a search path (e.g., from bundle)."""
        if path.exists() and path not in [p for p, _s in self._search_paths]:
            self._search_paths.append((path, source))

    def find(self, name: str) -> ModeDefinition | None:
        """Find a mode definition by name."""
        # Check cache first
        if name in self._cache:
            return self._cache[name]

        # Search paths
        for base_path, source_label in self._search_paths:
            mode_file = base_path / f"{name}.md"
            if mode_file.exists():
                mode_def = parse_mode_file(mode_file)
                if mode_def:
                    mode_def.source = source_label
                    self._cache[name] = mode_def
                    return mode_def

        return None

    def list_modes(self) -> list[tuple[str, str, str]]:
        """List all available modes as (name, description, source) tuples."""
        modes: dict[str, tuple[str, str]] = {}

        for base_path, source_label in self._search_paths:
            if not base_path.exists():
                continue
            for mode_file in base_path.glob("*.md"):
                name = mode_file.stem
                if name not in modes:  # First match wins (precedence)
                    mode_def = parse_mode_file(mode_file)
                    if mode_def:
                        mode_def.source = source_label
                        modes[name] = (mode_def.description, source_label)
                        self._cache[name] = mode_def

        return sorted((name, desc, source) for name, (desc, source) in modes.items())

    def get_shortcuts(self) -> dict[str, str]:
        """Get mapping of shortcut -> mode name for all modes with shortcuts."""
        shortcuts: dict[str, str] = {}

        for base_path, _source_label in self._search_paths:
            if not base_path.exists():
                continue
            for mode_file in base_path.glob("*.md"):
                name = mode_file.stem
                mode_def = self._cache.get(name) or parse_mode_file(mode_file)
                if mode_def:
                    self._cache[name] = mode_def
                    if mode_def.shortcut and mode_def.shortcut not in shortcuts:
                        shortcuts[mode_def.shortcut] = name

        return shortcuts

    def clear_cache(self) -> None:
        """Clear the mode definition cache."""
        self._cache.clear()


@hook(events=["provider:request", "tool:pre"], priority=10)
class ModeHooks:
    """Generic mode enforcement via hooks."""

    name = "mode_hooks"

    def __init__(self) -> None:
        self.discovery = ModeDiscovery()
        self.warned_tools: set[str] = set()
        self.infrastructure_tools: set[str] = {"mode", "todo"}
        self._active_mode: str | None = None
        self._require_approval_tools: set[str] = set()

    def _get_active_mode(self) -> ModeDefinition | None:
        """Get the currently active mode definition.

        Updates _require_approval_tools for approval hook integration.
        This uses the generic key that approval hook respects, allowing modes to
        drive approval policy without the approval hook knowing about modes.
        """
        mode_name = self._active_mode
        if not mode_name:
            # Clear approval requirements when no mode is active
            self._require_approval_tools = set()
            return None

        mode = self.discovery.find(mode_name)
        if mode:
            # Populate generic approval key - approval hook checks this
            self._require_approval_tools = set(mode.confirm_tools)
        else:
            self._require_approval_tools = set()

        return mode

    async def handle(self, event: str, data: dict) -> HookResult:
        """Dispatch to the appropriate handler based on event type."""
        if event == "provider:request":
            return await self._handle_provider_request(event, data)
        elif event == "tool:pre":
            return await self._handle_tool_pre(event, data)
        return HookResult(action=HookAction.CONTINUE)

    async def _handle_provider_request(self, _event: str, _data: dict) -> HookResult:
        """Inject mode context on every provider request."""
        mode = self._get_active_mode()
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
        mode = self._get_active_mode()
        if not mode:
            return HookResult(action=HookAction.CONTINUE)

        tool_name = data.get("tool_name", "")

        # Infrastructure tools: always bypass the cascade
        if tool_name in self.infrastructure_tools:
            return HookResult(action=HookAction.CONTINUE)

        # Safe tools: always allow
        if tool_name in mode.safe_tools:
            return HookResult(action=HookAction.CONTINUE)

        # Explicitly blocked tools: always deny
        if tool_name in mode.block_tools:
            return HookResult(
                action=HookAction.DENY,
                reason=f"Mode '{mode.name}': '{tool_name}' is blocked. {mode.description}",
            )

        # Confirm tools: let approval hook handle it
        # (_require_approval_tools is already set by _get_active_mode)
        if tool_name in mode.confirm_tools:
            return HookResult(action=HookAction.CONTINUE)

        # Warn-first tools: warn once, then allow
        if tool_name in mode.warn_tools:
            warn_key = f"{mode.name}:{tool_name}"
            if warn_key not in self.warned_tools:
                self.warned_tools.add(warn_key)
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

    def reset_warnings(self) -> None:
        """Reset warned tools (called when switching modes)."""
        self.warned_tools.clear()


# Exports for external use
__all__ = [
    "ModeDefinition",
    "ModeDiscovery",
    "ModeHooks",
    "parse_mode_file",
]
