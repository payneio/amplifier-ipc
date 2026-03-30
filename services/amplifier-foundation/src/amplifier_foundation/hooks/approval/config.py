"""Configuration and rule matching for approval hook."""

from __future__ import annotations

import fnmatch
from typing import Any

# Default rules if none provided
DEFAULT_RULES = [
    {"pattern": "ls*", "action": "auto_approve", "description": "List files is safe"},
    {
        "pattern": "pwd",
        "action": "auto_approve",
        "description": "Print working directory is safe",
    },
    {"pattern": "echo*", "action": "auto_approve", "description": "Echo is safe"},
]


def check_auto_action(
    rules: list[dict[str, Any]], tool_name: str, arguments: dict[str, Any]
) -> str | None:
    """Check if tool matches auto-approval rules.

    Args:
        rules: List of rule dictionaries
        tool_name: Name of the tool
        arguments: Tool arguments

    Returns:
        Action string ("auto_approve", "auto_deny") or None
    """
    for rule in rules:
        action = rule.get("action")
        if not action:
            continue

        # Tool-name-based matching: rule has a "tool" key
        tool_match = rule.get("tool")
        if tool_match and tool_match == tool_name:
            return action

        # For bash tool, also check command patterns
        if tool_name == "bash":
            pattern = rule.get("pattern", "")
            if pattern:
                command = arguments.get("command", "")
                # Match command against glob pattern (case-insensitive)
                if fnmatch.fnmatch(command.lower(), pattern.lower()):
                    return action

    return None
