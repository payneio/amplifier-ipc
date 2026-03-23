"""Streaming display handler for host event rendering."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from amplifier_ipc.host.events import (
    ChildSessionEndEvent,
    ChildSessionEvent,
    ChildSessionStartEvent,
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamContentBlockEndEvent,
    StreamContentBlockStartEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
    TodoUpdateEvent,
    ToolCallEvent,
    ToolResultEvent,
)

__all__ = ["StreamingDisplay"]

# Indentation applied per child-session nesting level.
_NESTING_INDENT = "    "  # 4 spaces


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
        self._show_token_usage = (
            show_token_usage  # reserved for future token-usage rendering
        )
        self._response: str | None = None
        self._in_thinking_block: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def response(self) -> str | None:
        """The final response text from the most recent CompleteEvent, or None."""
        return self._response

    def handle_event(self, event: HostEvent) -> None:
        """Dispatch a host event to the appropriate handler."""
        if isinstance(event, ChildSessionStartEvent):
            self._handle_child_session_start(event)
        elif isinstance(event, ChildSessionEndEvent):
            pass  # silent
        elif isinstance(event, ChildSessionEvent):
            self._handle_child_session_event(event)
        elif isinstance(event, StreamTokenEvent):
            self._handle_token(event)
        elif isinstance(event, StreamThinkingEvent):
            self._handle_thinking(event)
        elif isinstance(event, StreamContentBlockStartEvent):
            self._handle_content_block_start(event)
        elif isinstance(event, StreamContentBlockEndEvent):
            self._handle_content_block_end(event)
        elif isinstance(event, StreamToolCallStartEvent):
            self._handle_tool_call_start(event)
        elif isinstance(event, ToolCallEvent):
            self._handle_tool_call(event)
        elif isinstance(event, ToolResultEvent):
            self._handle_tool_result(event)
        elif isinstance(event, TodoUpdateEvent):
            self._handle_todo_update(event)
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

    def _handle_content_block_start(self, event: StreamContentBlockStartEvent) -> None:
        """Print brain emoji + 'Thinking...' header and double-line border for thinking blocks."""
        if event.block_type == "thinking" and self._show_thinking:
            self._in_thinking_block = True
            border = "\u2554" + "\u2550" * 50 + "\u2557"  # ╔══...══╗
            self._console.print("\U0001f9e0 Thinking...", style="dim", markup=False)
            self._console.print(border, style="dim", markup=False)

    def _handle_content_block_end(self, event: StreamContentBlockEndEvent) -> None:
        """Print closing double-line border for thinking blocks."""
        if event.block_type == "thinking" and self._in_thinking_block:
            self._in_thinking_block = False
            border = "\u255a" + "\u2550" * 50 + "\u255d"  # ╚══...══╝
            self._console.print("\n" + border, style="dim", markup=False)

    def _handle_thinking(self, event: StreamThinkingEvent) -> None:
        """Print thinking text in cyan dim style when show_thinking is enabled."""
        if self._show_thinking:
            self._console.print(event.thinking, end="", style="cyan dim", markup=False)

    def _handle_tool_call_start(self, event: StreamToolCallStartEvent) -> None:
        """Print the tool name for a tool call start event."""
        self._console.print(f"\n[dim]\u2699 {event.tool_name}[/dim]")

    def _handle_tool_call(self, event: ToolCallEvent) -> None:
        """Print tool name header and YAML-formatted arguments."""
        self._console.print(f"\n\u2699 [bold]{event.tool_name}[/bold]")
        items = list(event.arguments.items())
        display_items = items[:10]
        remaining = len(items) - len(display_items)
        for key, value in display_items:
            truncated = str(value)[:200]
            self._console.print(
                f"   [dim]{key}:[/dim] {truncated}",
                markup=True,
                highlight=False,
            )
        if remaining > 0:
            self._console.print(f"   [dim]... ({remaining} more)[/dim]")

    def _handle_tool_result(self, event: ToolResultEvent) -> None:
        """Print tool result with success/failure icon and truncated output."""
        if event.success:
            icon = "\u2705"
            style = "green"
        else:
            icon = "\u274c"
            style = "red"
        self._console.print(f"{icon} {event.tool_name}", style=style, markup=False)
        lines = event.output.split("\n")
        display_lines = lines[:10]
        remaining = len(lines) - len(display_lines)
        for line in display_lines:
            self._console.print(
                f"   {line[:200]}", style="dim", markup=False, highlight=False
            )
        if remaining > 0:
            self._console.print(
                f"   ... ({remaining} more lines)",
                style="dim",
                markup=False,
                highlight=False,
            )

    def _handle_todo_update(self, event: TodoUpdateEvent) -> None:
        """Print a bordered todo list box with status symbols and a progress bar."""
        if not event.todos:
            return

        # Status symbols
        symbols: dict[str, str] = {
            "completed": "\u2713",  # ✓ checkmark
            "in_progress": "\u25b6",  # ▶ play
            "pending": "\u25cb",  # ○ circle
        }

        total = len(event.todos)
        completed_count = sum(1 for t in event.todos if t.get("status") == "completed")

        # Layout constants
        box_width = 50  # Inner content width (chars between the │ borders)
        bar_width = 20  # Width of the progress bar in block chars
        full_mode_threshold = 7  # Show individual items up to this count

        top_border = "\u250c" + "\u2500" * box_width + "\u2510"
        bottom_border = "\u2514" + "\u2500" * box_width + "\u2518"

        self._console.print(top_border, markup=False)

        if total <= full_mode_threshold:
            # Full mode: show each todo item
            for todo in event.todos:
                status = todo.get("status", "pending")
                symbol = symbols.get(status, " ")
                content = str(todo.get("content", ""))
                # Truncate content to fit box
                inner_width = box_width - 4  # 2 for "│ " and 2 for symbol + space
                if len(content) > inner_width:
                    content = content[: inner_width - 3] + "..."
                line = f"\u2502 {symbol} {content}"
                # Pad to fill the box
                padding = box_width - len(f" {symbol} {content}")
                if padding > 0:
                    line += " " * padding
                line += "\u2502"
                self._console.print(line, markup=False)
        else:
            # Condensed mode: show summary counts
            in_progress_count = sum(
                1 for t in event.todos if t.get("status") == "in_progress"
            )
            pending_count = sum(1 for t in event.todos if t.get("status") == "pending")
            summary = (
                f"\u2502 {symbols['completed']} {completed_count} completed  "
                f"{symbols['in_progress']} {in_progress_count} in progress  "
                f"{symbols['pending']} {pending_count} pending"
            )
            # summary starts with "│" (1 char border) then inner content;
            # subtract 1 to get inner content length, then pad to box_width.
            padding = box_width - (len(summary) - 1)
            if padding > 0:
                summary += " " * padding
            summary += "\u2502"
            self._console.print(summary, markup=False)

        # Progress bar
        filled = int(bar_width * completed_count / total) if total > 0 else 0
        empty = bar_width - filled
        bar = "\u2588" * filled + "\u2591" * empty
        progress_text = f"{completed_count}/{total}"
        progress_line = f"\u2502 {bar} {progress_text}"
        padding = box_width - len(f" {bar} {progress_text}")
        if padding > 0:
            progress_line += " " * padding
        progress_line += "\u2502"
        self._console.print(progress_line, markup=False)

        self._console.print(bottom_border, markup=False)

    def _handle_error(self, event: ErrorEvent) -> None:
        """Print error message in red with cross icon."""
        self._console.print(f"\u2717 {event.message}", style="red", markup=False)

    def _handle_complete(self, event: CompleteEvent) -> None:
        """Store the final response and print a newline."""
        self._response = event.result
        self._console.print()

    # ------------------------------------------------------------------
    # Child session handlers
    # ------------------------------------------------------------------

    def _handle_child_session_start(self, event: ChildSessionStartEvent) -> None:
        """Print gear icon and delegate header with agent name in bold cyan."""
        indent = _NESTING_INDENT * (event.depth - 1)
        self._console.print(
            f"{indent}\u2699 [bold cyan]delegate -> {event.agent_name}[/bold cyan]"
        )

    def _handle_child_session_event(self, event: ChildSessionEvent) -> None:
        """Render inner event with nesting indentation using an isolated buffer."""
        if event.inner is None:
            return

        inner_buf = StringIO()
        inner_width = max(40, self._console.width - 4 * event.depth)
        inner_console = Console(file=inner_buf, no_color=True, width=inner_width)
        inner_display = StreamingDisplay(
            console=inner_console,
            show_thinking=self._show_thinking,
            show_token_usage=self._show_token_usage,
        )
        inner_display.handle_event(event.inner)

        inner_output = inner_buf.getvalue()
        indent = _NESTING_INDENT * event.depth
        for line in inner_output.split("\n"):
            if line.strip():
                self._console.print(indent + line, markup=False, highlight=False)
