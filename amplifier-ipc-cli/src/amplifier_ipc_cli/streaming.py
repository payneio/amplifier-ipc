"""Streaming display handler for host event rendering."""

from __future__ import annotations

from rich.console import Console

from amplifier_ipc_host.events import (
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)

__all__ = ["StreamingDisplay"]


class StreamingDisplay:
    """Renders host streaming events to a Rich console.

    Args:
        console: Rich Console instance for output.
        show_thinking: Whether to render StreamThinkingEvent text (default True).
        show_token_usage: Whether to display token usage information (default True).
    """

    def __init__(
        self,
        console: Console,
        show_thinking: bool = True,
        show_token_usage: bool = True,
    ) -> None:
        self._console = console
        self._show_thinking = show_thinking
        self._show_token_usage = show_token_usage
        self._response: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def response(self) -> str | None:
        """The final response text from the most recent CompleteEvent, or None."""
        return self._response

    def handle_event(self, event: HostEvent) -> None:
        """Dispatch a host event to the appropriate handler."""
        if isinstance(event, StreamTokenEvent):
            self._handle_token(event)
        elif isinstance(event, StreamThinkingEvent):
            self._handle_thinking(event)
        elif isinstance(event, StreamToolCallStartEvent):
            self._handle_tool_call_start(event)
        elif isinstance(event, ErrorEvent):
            self._handle_error(event)
        elif isinstance(event, CompleteEvent):
            self._handle_complete(event)

    # ------------------------------------------------------------------
    # Private handlers
    # ------------------------------------------------------------------

    def _handle_token(self, event: StreamTokenEvent) -> None:
        """Print token text without markup processing."""
        self._console.print(event.token, end="", markup=False, highlight=False)

    def _handle_thinking(self, event: StreamThinkingEvent) -> None:
        """Print thinking text in cyan dim style when show_thinking is enabled."""
        if self._show_thinking:
            self._console.print(event.thinking, end="", style="cyan dim", markup=False)

    def _handle_tool_call_start(self, event: StreamToolCallStartEvent) -> None:
        """Print the tool name for a tool call start event."""
        self._console.print(f"\n[tool] {event.tool_name}", markup=False)

    def _handle_error(self, event: ErrorEvent) -> None:
        """Print error message in red."""
        self._console.print(event.message, style="red", markup=False)

    def _handle_complete(self, event: CompleteEvent) -> None:
        """Store the final response and print a newline."""
        self._response = event.result
        self._console.print()
