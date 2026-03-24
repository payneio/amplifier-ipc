"""Streaming display handler for host event rendering."""

from __future__ import annotations

import time
from io import StringIO
from typing import Any

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

# Default truncation limits for tool call/result rendering.
_DEFAULT_TOOL_ARG_VALUE_LEN = 200
_DEFAULT_TOOL_ARGS_COUNT = 10
_DEFAULT_TOOL_RESULT_LINES = 10
_DEFAULT_TOOL_RESULT_LINE_LEN = 200
_DEFAULT_RESULT_PREVIEW_LEN = 500

# Verbose truncation limits — more generous so full detail is visible.
_VERBOSE_TOOL_ARG_VALUE_LEN = 2000
_VERBOSE_TOOL_ARGS_COUNT = 50
_VERBOSE_TOOL_RESULT_LINES = 50
_VERBOSE_TOOL_RESULT_LINE_LEN = 500
_VERBOSE_RESULT_PREVIEW_LEN = 2000


class StreamingDisplay:
    """Renders host streaming events to a Rich console.

    Args:
        console: Rich Console instance for output.
        show_thinking: Whether to render StreamThinkingEvent text (default True).
        show_token_usage: Whether to display token usage information (default True).
        trace_mode: If True, accumulate tool call and delegation trace entries
            alongside normal rendering.  Access results via :attr:`trace` and
            :attr:`trace_metadata` after the run completes (default False).
        verbose: If True, expand truncation limits for tool arguments and
            results, and show additional session lifecycle detail (default False).
    """

    def __init__(
        self,
        console: Console,
        show_thinking: bool = True,
        show_token_usage: bool = True,
        trace_mode: bool = False,
        verbose: bool = False,
    ) -> None:
        self._console = console
        self._show_thinking = show_thinking
        self._show_token_usage = (
            show_token_usage  # reserved for future token-usage rendering
        )
        self._trace_mode = trace_mode
        self._verbose = verbose
        self._response: str | None = None
        self._in_thinking_block: bool = False

        # ------------------------------------------------------------------
        # Trace accumulation state (populated when trace_mode=True)
        # ------------------------------------------------------------------
        self._trace: list[dict[str, Any]] = []
        self._start_time: float = time.monotonic()

        # Pending tool call: set by ToolCallEvent, consumed by ToolResultEvent.
        self._pending_tool_name: str | None = None
        self._pending_tool_args: dict[str, Any] = {}
        self._pending_tool_start: float | None = None

        # Pending delegations keyed by session_id.
        # Value: (agent_name, instruction_preview, monotonic start time)
        self._pending_delegations: dict[str, tuple[str, str, float]] = {}

        # Running totals for metadata
        self._tool_call_count: int = 0
        self._delegation_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def response(self) -> str | None:
        """The final response text from the most recent CompleteEvent, or None."""
        return self._response

    @property
    def trace(self) -> list[dict[str, Any]]:
        """Accumulated execution trace entries.

        Each entry is a dict with at minimum a ``"type"`` key.  Populated only
        when ``trace_mode=True``.

        Tool call entry shape::

            {
                "type": "tool_call",
                "tool": "<tool_name>",
                "args": {<arguments>},
                "result_preview": "<truncated output>",
                "duration_ms": <int>,
            }

        Delegation entry shape::

            {
                "type": "delegation",
                "agent": "<agent_name>",
                "instruction_preview": "<empty — not available in events>",
                "duration_ms": <int>,
            }
        """
        return list(self._trace)

    @property
    def trace_metadata(self) -> dict[str, Any]:
        """Summary metadata for the current execution.

        Returns a dict with ``total_tool_calls``, ``total_delegations``, and
        ``duration_ms`` (elapsed milliseconds since this :class:`StreamingDisplay`
        was constructed).
        """
        duration_ms = int((time.monotonic() - self._start_time) * 1000)
        return {
            "total_tool_calls": self._tool_call_count,
            "total_delegations": self._delegation_count,
            "duration_ms": duration_ms,
        }

    def handle_event(self, event: HostEvent) -> None:
        """Dispatch a host event to the appropriate handler."""
        if isinstance(event, ChildSessionStartEvent):
            self._handle_child_session_start(event)
        elif isinstance(event, ChildSessionEndEvent):
            self._handle_child_session_end(event)
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
        self._console.print(f"\n[dim]\U0001f527 {event.tool_name}[/dim]")
        self._saw_tool_call_start = True

    def _handle_tool_call(self, event: ToolCallEvent) -> None:
        """Print tool call arguments.

        If a preceding ``StreamToolCallStartEvent`` already printed the tool
        name, we skip the header to avoid duplicate display.  When no start
        event was received (e.g. non-streaming execution), we still show the
        full header.
        """
        if not getattr(self, "_saw_tool_call_start", False):
            # No start event preceded this \u2014 show the tool name header.
            self._console.print(f"\n\U0001f527 [bold]{event.tool_name}[/bold]")
        self._saw_tool_call_start = False

        arg_value_len = (
            _VERBOSE_TOOL_ARG_VALUE_LEN
            if self._verbose
            else _DEFAULT_TOOL_ARG_VALUE_LEN
        )
        args_count = (
            _VERBOSE_TOOL_ARGS_COUNT if self._verbose else _DEFAULT_TOOL_ARGS_COUNT
        )

        items = list(event.arguments.items())
        display_items = items[:args_count]
        remaining = len(items) - len(display_items)
        for key, value in display_items:
            truncated = str(value)[:arg_value_len]
            self._console.print(
                f"   [dim]{key}:[/dim] {truncated}",
                markup=True,
                highlight=False,
            )
        if remaining > 0:
            self._console.print(f"   [dim]... ({remaining} more)[/dim]")

        # Record start time and arguments for trace
        if self._trace_mode:
            self._pending_tool_name = event.tool_name
            self._pending_tool_args = dict(event.arguments)
            self._pending_tool_start = time.monotonic()

    def _handle_tool_result(self, event: ToolResultEvent) -> None:
        """Print tool result with success/failure icon and truncated output."""
        if event.success:
            icon = "\u2705"
            style = "green"
        else:
            icon = "\u274c"
            style = "red"
        self._console.print(f"{icon} {event.tool_name}", style=style, markup=False)

        result_lines = (
            _VERBOSE_TOOL_RESULT_LINES if self._verbose else _DEFAULT_TOOL_RESULT_LINES
        )
        result_line_len = (
            _VERBOSE_TOOL_RESULT_LINE_LEN
            if self._verbose
            else _DEFAULT_TOOL_RESULT_LINE_LEN
        )

        lines = event.output.split("\n")
        display_lines = lines[:result_lines]
        remaining = len(lines) - len(display_lines)
        for line in display_lines:
            self._console.print(
                f"   {line[:result_line_len]}",
                style="dim",
                markup=False,
                highlight=False,
            )
        if remaining > 0:
            self._console.print(
                f"   ... ({remaining} more lines)",
                style="dim",
                markup=False,
                highlight=False,
            )

        # Complete the pending trace entry
        if self._trace_mode and self._pending_tool_start is not None:
            duration_ms = int((time.monotonic() - self._pending_tool_start) * 1000)
            preview_len = (
                _VERBOSE_RESULT_PREVIEW_LEN
                if self._verbose
                else _DEFAULT_RESULT_PREVIEW_LEN
            )
            self._trace.append(
                {
                    "type": "tool_call",
                    "tool": event.tool_name,
                    "args": self._pending_tool_args,
                    "result_preview": event.output[:preview_len],
                    "duration_ms": duration_ms,
                }
            )
            self._tool_call_count += 1
            # Reset pending state
            self._pending_tool_name = None
            self._pending_tool_args = {}
            self._pending_tool_start = None

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
        """Print gear icon and delegate header; record delegation start for trace."""
        indent = _NESTING_INDENT * (event.depth - 1)
        self._console.print(
            f"{indent}\U0001f527 [bold cyan]delegate -> {event.agent_name}[/bold cyan]"
        )
        if self._verbose:
            self._console.print(f"{indent}  [dim]session_id: {event.session_id}[/dim]")
        if self._trace_mode:
            # ChildSessionStartEvent has no instruction field — use empty preview.
            self._pending_delegations[event.session_id] = (
                event.agent_name,
                "",
                time.monotonic(),
            )

    def _handle_child_session_end(self, event: ChildSessionEndEvent) -> None:
        """Complete a delegation trace entry when the child session ends."""
        if not self._trace_mode:
            return

        start_info = self._pending_delegations.pop(event.session_id, None)
        if start_info is not None:
            agent_name, instruction_preview, start_time = start_info
            duration_ms = int((time.monotonic() - start_time) * 1000)
            self._trace.append(
                {
                    "type": "delegation",
                    "agent": agent_name,
                    "instruction_preview": instruction_preview,
                    "duration_ms": duration_ms,
                }
            )
            self._delegation_count += 1

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
            trace_mode=self._trace_mode,
            verbose=self._verbose,
        )
        inner_display.handle_event(event.inner)

        if self._trace_mode:
            self._trace.extend(inner_display.trace)
            self._tool_call_count += inner_display._tool_call_count
            self._delegation_count += inner_display._delegation_count

        inner_output = inner_buf.getvalue()
        indent = _NESTING_INDENT * event.depth
        for line in inner_output.split("\n"):
            if line.strip():
                self._console.print(indent + line, markup=False, highlight=False)
