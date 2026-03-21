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
    # For bash tool, check command patterns
    if tool_name == "bash":
        command = arguments.get("command", "")

        for rule in rules:
            pattern = rule.get("pattern", "")
            action = rule.get("action")

            if not pattern or not action:
                continue

            # Match command against glob pattern (case-insensitive)
            if fnmatch.fnmatch(command.lower(), pattern.lower()):
                return action

    return None
