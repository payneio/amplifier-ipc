"""CLI display system with Rich formatting and nesting depth support."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.text import Text

__all__ = ["CLIDisplaySystem", "format_throttle_warning"]

# Indentation applied per nesting level.
NESTING_INDENT = "    "  # 4 spaces

# Color mapping per message level.
_LEVEL_COLORS: dict[str, str] = {
    "info": "cyan",
    "warning": "yellow",
    "error": "red",
}


def _extract_tool_name(source: str) -> str:
    """Extract the tool name from a source string.

    If *source* contains a colon, returns the part after the last colon.
    Otherwise returns *source* unchanged.

    Examples::

        >>> _extract_tool_name("hook:python-check")
        'python-check'
        >>> _extract_tool_name("my-tool")
        'my-tool'
    """
    if ":" in source:
        return source.rsplit(":", 1)[-1]
    return source


class CLIDisplaySystem:
    """Display system for the Amplifier IPC CLI.

    Supports nesting depth tracking and Rich-formatted message output.

    Args:
        console: Optional Rich Console to use.  Defaults to a new stderr
                 console.  Pass a custom Console (e.g. backed by StringIO)
                 for testing.
    """

    def __init__(self, console: Console | None = None) -> None:
        self._console: Console = (
            console if console is not None else Console(stderr=True)
        )
        self._depth: int = 0

    # ------------------------------------------------------------------
    # Nesting depth API
    # ------------------------------------------------------------------

    @property
    def nesting_depth(self) -> int:
        """Current nesting depth (always >= 0)."""
        return self._depth

    def push_nesting(self) -> None:
        """Increment the nesting depth by one."""
        self._depth += 1

    def pop_nesting(self) -> None:
        """Decrement the nesting depth by one (minimum 0)."""
        if self._depth > 0:
            self._depth -= 1

    # ------------------------------------------------------------------
    # Message display
    # ------------------------------------------------------------------

    def show_message(self, message: str, level: str, source: str) -> None:
        """Display a formatted message.

        Args:
            message: The message text (may contain newlines).
            level:   Severity level — ``"info"``, ``"warning"``, or
                     ``"error"``.  Determines the colour of the tool label.
            source:  Source identifier.  The tool name is extracted as the
                     portion after the last colon (e.g. ``"hook:python-check"``
                     → ``"python-check"``).
        """
        tool_name = _extract_tool_name(source)
        color = _LEVEL_COLORS.get(level, "white")
        indent = NESTING_INDENT * self._depth

        lines = message.splitlines() or [""]
        for i, line in enumerate(lines):
            # The tool label prefix appears only on the first line.
            if i == 0:
                text = Text()
                text.append(indent)
                text.append(tool_name, style=color)
                text.append(": ")
                text.append(line)
            else:
                # Continuation lines are indented to align with the message body.
                text = Text()
                text.append(indent + " " * (len(tool_name) + len(": ")))
                text.append(line)
            self._console.print(text, end="\n")


# ---------------------------------------------------------------------------
# Standalone utility
# ---------------------------------------------------------------------------


def format_throttle_warning(payload: dict[str, Any]) -> str:
    """Format a provider throttle event into a human-readable warning string.

    Args:
        payload: Dictionary containing at minimum ``provider`` and ``delay``
                 keys.  Optional ``remaining`` and ``limit`` keys trigger a
                 percentage calculation.

    Returns:
        A formatted string describing the throttle event.

    Examples::

        >>> p = {"provider": "anthropic", "remaining": 50, "limit": 100, "delay": 30}
        >>> format_throttle_warning(p)
        'Provider anthropic throttled: 50% remaining — waiting 30s'

        >>> format_throttle_warning({"provider": "openai", "delay": 15})
        'Provider openai throttled — waiting 15s'
    """
    provider: str = payload.get("provider", "unknown")
    delay: int | float = payload.get("delay", 0)
    remaining: int | float | None = payload.get("remaining")
    limit: int | float | None = payload.get("limit")

    if remaining is not None and limit is not None and limit > 0:
        percentage = int(round(remaining / limit * 100))
        return (
            f"Provider {provider} throttled: {percentage}% remaining — waiting {delay}s"
        )

    return f"Provider {provider} throttled — waiting {delay}s"
