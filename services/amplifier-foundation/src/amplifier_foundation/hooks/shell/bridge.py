"""Main bridge module for shell hooks.

Coordinates loading, matching, execution, and translation of hooks.
Ported for IPC mode — removed amplifier_lite.session.Session dependency.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from amplifier_ipc.protocol.models import HookAction, HookResult

from .executor import HookExecutor
from .loader import HookConfigLoader
from .matcher import MatcherGroup
from .translator import DataTranslator

logger = logging.getLogger(__name__)


class ShellHookBridge:
    """Bridge that executes shell hooks in Amplifier."""

    # Map Amplifier events to Claude Code event names
    CLAUDE_EVENT_MAP = {
        "tool:pre": "PreToolUse",
        "tool:post": "PostToolUse",
        "prompt:submit": "UserPromptSubmit",
        "session:start": "SessionStart",
        "session:end": "SessionEnd",
        "prompt:complete": "Stop",
        "context:pre_compact": "PreCompact",
        "approval:required": "PermissionRequest",
        "session:resume": "SessionStart",
        "user:notification": "Notification",
    }

    # Events that support blocking/modification
    BLOCKING_EVENTS = {
        "PreToolUse",
        "UserPromptSubmit",
        "Stop",
        "PermissionRequest",
    }

    # Events that support context injection
    CONTEXT_INJECTION_EVENTS = {
        "PreToolUse",
        "PostToolUse",
        "UserPromptSubmit",
        "SessionStart",
        "PreCompact",
    }

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize bridge.

        Args:
            config: Module configuration
        """
        self.config = config
        self.enabled = config.get("enabled", True)

        # Discover hooks directory
        project_dir = Path(config.get("working_dir", ".")).resolve()
        hooks_dir = project_dir / ".amplifier" / "hooks"

        if not hooks_dir.exists():
            logger.info("Hooks directory not found at %s", hooks_dir)
            self.hook_configs: dict[str, Any] = {"hooks": {}}
        else:
            loader = HookConfigLoader(hooks_dir)
            self.hook_configs = loader.load_all_configs()
            hook_events = list(self.hook_configs.get("hooks", {}).keys())
            logger.info("Loaded hook configs from %s: %s", hooks_dir, hook_events)

        self.project_dir = project_dir
        self.hooks_dir = hooks_dir
        self.translator = DataTranslator()
        self.executor: HookExecutor | None = None

        # Create matcher groups for each event
        self.matcher_groups: dict[str, MatcherGroup] = {}
        for event_name, matchers_config in self.hook_configs.get("hooks", {}).items():
            self.matcher_groups[event_name] = MatcherGroup(matchers_config)

        # Skill-scoped hooks
        self.skill_scoped_hooks: dict[str, dict[str, Any]] = {}
        self.skill_matcher_groups: dict[str, dict[str, MatcherGroup]] = {}

    def _get_executor(self, session_id: str = "unknown") -> HookExecutor:
        """Get or create executor."""
        if self.executor is None:
            self.executor = HookExecutor(self.project_dir, self.hooks_dir, session_id)
        return self.executor

    async def _execute_single_hook(
        self,
        hook_config: dict[str, Any],
        claude_data: dict[str, Any],
        executor: HookExecutor,
    ) -> dict[str, Any]:
        """Execute a single hook and return the result fields."""
        hook_type = hook_config.get("type", "command")

        if hook_type == "command":
            command = hook_config.get("command")
            if not command:
                return {"action": "continue"}

            timeout = hook_config.get("timeout", 30.0)
            logger.info("Executing command hook: %s", command)

            exit_code, stdout, stderr = await executor.execute(
                command, claude_data, timeout
            )
            result_fields = self.translator.from_claude_response(
                exit_code, stdout, stderr
            )

        else:
            logger.debug("Skipping unknown hook type: %s", hook_type)
            return {"action": "continue"}

        return result_fields

    async def _execute_hooks(
        self, amplifier_event: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute matching hooks for an event."""
        if not self.enabled:
            return {"action": "continue"}

        claude_event = self.CLAUDE_EVENT_MAP.get(amplifier_event)
        if not claude_event:
            return {"action": "continue"}

        if claude_event == "SessionStart":
            match_target = data.get("trigger", "startup")
        else:
            match_target = data.get("tool_name", data.get("name", ""))

        matching_groups: list[dict[str, Any]] = []

        if claude_event in self.matcher_groups:
            dir_groups = self.matcher_groups[claude_event].get_matching_groups(
                match_target
            )
            matching_groups.extend(dir_groups)

        for skill_name, skill_matchers in self.skill_matcher_groups.items():
            if claude_event in skill_matchers:
                skill_groups = skill_matchers[claude_event].get_matching_groups(
                    match_target
                )
                if skill_groups:
                    matching_groups.extend(skill_groups)

        if not matching_groups:
            return {"action": "continue"}

        claude_data = self.translator.to_claude_format(claude_event, data)
        session_id = data.get("session_id", "unknown")
        executor = self._get_executor(session_id)

        for matcher_group in matching_groups:
            hooks = matcher_group.get("hooks", [])
            parallel = matcher_group.get("parallel", False)

            if not hooks:
                continue

            if parallel:
                results = await asyncio.gather(
                    *[
                        self._execute_single_hook(hook, claude_data, executor)
                        for hook in hooks
                    ],
                    return_exceptions=True,
                )

                for result in results:
                    if isinstance(result, BaseException):
                        logger.warning("Hook failed with exception: %s", result)
                        continue

                    result_dict: dict[str, Any] = result  # type: ignore[assignment]
                    action = result_dict.get("action", "continue")
                    if action in ("deny", "modify", "inject_context"):
                        return result_dict

            else:
                for hook_config in hooks:
                    result_fields = await self._execute_single_hook(
                        hook_config, claude_data, executor
                    )

                    action = result_fields.get("action", "continue")
                    if action in ("deny", "modify", "inject_context"):
                        return result_fields

        return {"action": "continue"}

    @staticmethod
    def _to_hook_result(fields: dict[str, Any]) -> HookResult:
        """Build a HookResult from a dict with lowercase action strings."""
        action_str = fields.pop("action", "continue").upper()
        action = HookAction(action_str)
        return HookResult(action=action, **fields)

    async def handle(self, amplifier_event: str, data: dict[str, Any]) -> HookResult:
        """Handle any supported event."""
        return self._to_hook_result(await self._execute_hooks(amplifier_event, data))
