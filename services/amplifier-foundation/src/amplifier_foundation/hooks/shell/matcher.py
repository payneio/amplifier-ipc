"""Matcher for filtering hooks by tool name.

Implements Claude Code's regex-based matcher system.
"""

from __future__ import annotations

import re
from typing import Any


class HookMatcher:
    """Match tool names against Claude Code patterns."""

    def __init__(self, pattern: str):
        self.pattern = pattern
        self._compiled_regex = self._compile_pattern(pattern)

    def _compile_pattern(self, pattern: str) -> re.Pattern[str] | None:
        """Compile matcher pattern to regex."""
        if not pattern or pattern == "*":
            return None

        try:
            return re.compile(pattern, re.IGNORECASE)
        except re.error:
            return None

    def matches(self, tool_name: str) -> bool:
        """Check if tool name matches the pattern."""
        if self._compiled_regex is None and (not self.pattern or self.pattern == "*"):
            return True

        if self._compiled_regex:
            return bool(self._compiled_regex.fullmatch(tool_name))

        return tool_name.lower() == self.pattern.lower()


class MatcherGroup:
    """Group of matchers for a specific event."""

    def __init__(self, matchers_config: list[dict[str, Any]]):
        self.matcher_configs: list[tuple[HookMatcher, dict[str, Any]]] = []

        for matcher_config in matchers_config:
            pattern = matcher_config.get("matcher", "*")
            hooks = matcher_config.get("hooks", [])

            if hooks:
                matcher = HookMatcher(pattern)
                self.matcher_configs.append((matcher, matcher_config))

    def get_matching_hooks(self, tool_name: str) -> list[dict[str, Any]]:
        """Get all hooks that match the given tool name."""
        matching = []

        for matcher, config in self.matcher_configs:
            if matcher.matches(tool_name):
                matching.extend(config.get("hooks", []))

        return matching

    def get_matching_groups(self, tool_name: str) -> list[dict[str, Any]]:
        """Get all matcher groups that match the given tool name.

        Returns the full matcher config (including 'parallel' flag) for each
        matching group, not just the individual hooks.
        """
        matching = []

        for matcher, config in self.matcher_configs:
            if matcher.matches(tool_name):
                matching.append(config)

        return matching
