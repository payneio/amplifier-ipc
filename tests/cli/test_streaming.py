"""Tests for StreamingDisplay class in streaming.py."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from amplifier_ipc.host.events import (
    ChildSessionEndEvent,
    ChildSessionEvent,
    ChildSessionStartEvent,
    CompleteEvent,
    StreamContentBlockEndEvent,
    StreamContentBlockStartEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)


def _make_console() -> tuple[Console, StringIO]:
    """Create a Console backed by StringIO for output capture."""
    buf = StringIO()
    console = Console(file=buf, no_color=True, width=120)
    return console, buf


# ---------------------------------------------------------------------------
# Test 1: test_streaming_display_token
# ---------------------------------------------------------------------------


class TestStreamingDisplayToken:
    def test_streaming_display_token(self) -> None:
        """StreamTokenEvent should print token text without markup."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = StreamTokenEvent(token="Hello, world!")
        display.handle_event(event)

        output = buf.getvalue()
        assert "Hello, world!" in output


# ---------------------------------------------------------------------------
# Test 2: test_streaming_display_thinking (enabled)
# ---------------------------------------------------------------------------


class TestStreamingDisplayThinkingEnabled:
    def test_streaming_display_thinking(self) -> None:
        """StreamThinkingEvent should print thinking text when show_thinking=True."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console, show_thinking=True)

        event = StreamThinkingEvent(thinking="Deep thoughts here")
        display.handle_event(event)

        output = buf.getvalue()
        assert "Deep thoughts here" in output


# ---------------------------------------------------------------------------
# Test 3: test_streaming_display_thinking_hidden (disabled)
# ---------------------------------------------------------------------------


class TestStreamingDisplayThinkingHidden:
    def test_streaming_display_thinking_hidden(self) -> None:
        """StreamThinkingEvent should NOT print thinking text when show_thinking=False."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console, show_thinking=False)

        event = StreamThinkingEvent(thinking="Hidden thoughts")
        display.handle_event(event)

        output = buf.getvalue()
        assert "Hidden thoughts" not in output


# ---------------------------------------------------------------------------
# Test 4: test_streaming_display_tool_call_start
# ---------------------------------------------------------------------------


class TestStreamingDisplayToolCallStart:
    def test_streaming_display_tool_call_start(self) -> None:
        """StreamToolCallStartEvent should print the tool name."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = StreamToolCallStartEvent(tool_name="my_awesome_tool")
        display.handle_event(event)

        output = buf.getvalue()
        assert "my_awesome_tool" in output


# ---------------------------------------------------------------------------
# Test 5: test_streaming_display_complete
# ---------------------------------------------------------------------------


class TestStreamingDisplayComplete:
    def test_streaming_display_complete(self) -> None:
        """CompleteEvent should store response in display.response and print a newline."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        # Before CompleteEvent, response should be None
        assert display.response is None

        event = CompleteEvent(result="The final answer")
        display.handle_event(event)

        # After CompleteEvent, response should be stored
        assert display.response == "The final answer"

        # A newline should have been written
        output = buf.getvalue()
        assert "\n" in output


# ---------------------------------------------------------------------------
# Test 6: test_tool_call_renders_name_and_args
# ---------------------------------------------------------------------------


class TestToolCallRendersNameAndArgs:
    def test_tool_call_renders_name_and_args(self) -> None:
        """ToolCallEvent should print tool name and key-value argument pairs."""
        from amplifier_ipc.cli.streaming import StreamingDisplay
        from amplifier_ipc.host.events import ToolCallEvent

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = ToolCallEvent(
            tool_name="bash",
            arguments={"command": "pytest tests/ -v", "timeout": 30},
        )
        display.handle_event(event)

        output = buf.getvalue()
        assert "bash" in output
        assert "command" in output
        assert "pytest tests/ -v" in output
        assert "timeout" in output


# ---------------------------------------------------------------------------
# Test 7: test_tool_call_truncates_long_args
# ---------------------------------------------------------------------------


class TestToolCallTruncatesLongArgs:
    def test_tool_call_truncates_long_args(self) -> None:
        """ToolCallEvent with 15 args should show first 10 and a truncation indicator."""
        from amplifier_ipc.cli.streaming import StreamingDisplay
        from amplifier_ipc.host.events import ToolCallEvent

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        arguments = {f"arg_{i}": f"value_{i}" for i in range(15)}
        event = ToolCallEvent(tool_name="complex_tool", arguments=arguments)
        display.handle_event(event)

        output = buf.getvalue()
        assert "complex_tool" in output
        # Should have a truncation indicator showing more args exist
        assert "more" in output


# ---------------------------------------------------------------------------
# Test 8: test_tool_result_success
# ---------------------------------------------------------------------------


class TestToolResultSuccess:
    def test_tool_result_success(self) -> None:
        """ToolResultEvent with success=True should show green styling with tool name and output."""
        from amplifier_ipc.cli.streaming import StreamingDisplay
        from amplifier_ipc.host.events import ToolResultEvent

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = ToolResultEvent(
            tool_name="bash",
            success=True,
            output="6 passed in 1.2s",
        )
        display.handle_event(event)

        output = buf.getvalue()
        assert "bash" in output
        assert "6 passed in 1.2s" in output


# ---------------------------------------------------------------------------
# Test 9: test_tool_result_failure
# ---------------------------------------------------------------------------


class TestToolResultFailure:
    def test_tool_result_failure(self) -> None:
        """ToolResultEvent with success=False should show red styling with tool name and output."""
        from amplifier_ipc.cli.streaming import StreamingDisplay
        from amplifier_ipc.host.events import ToolResultEvent

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = ToolResultEvent(
            tool_name="bash",
            success=False,
            output="command not found: pytest",
        )
        display.handle_event(event)

        output = buf.getvalue()
        assert "bash" in output
        assert "command not found" in output


# ---------------------------------------------------------------------------
# Test 10: test_tool_result_truncates_long_output
# ---------------------------------------------------------------------------


class TestToolResultTruncatesLongOutput:
    def test_tool_result_truncates_long_output(self) -> None:
        """ToolResultEvent with 50 lines of output should truncate to max 10 lines plus indicator."""
        from amplifier_ipc.cli.streaming import StreamingDisplay
        from amplifier_ipc.host.events import ToolResultEvent

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        lines = [f"line_{i}" for i in range(50)]
        event = ToolResultEvent(
            tool_name="read_file",
            success=True,
            output="\n".join(lines),
        )
        display.handle_event(event)

        output = buf.getvalue()
        assert "read_file" in output
        # Output lines (prefixed with '   ') should be at most 12
        # (10 content lines + 1 header line + 1 truncation indicator)
        output_lines = output.splitlines()
        assert len(output_lines) <= 12


# ---------------------------------------------------------------------------
# Test 11: test_todo_update_renders_items
# ---------------------------------------------------------------------------


class TestTodoUpdateRendersItems:
    def test_todo_update_renders_items(self) -> None:
        """TodoUpdateEvent with 3 items should render content strings and progress bar."""
        from amplifier_ipc.cli.streaming import StreamingDisplay
        from amplifier_ipc.host.events import TodoUpdateEvent

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = TodoUpdateEvent(
            todos=[
                {
                    "content": "Task one",
                    "status": "completed",
                    "activeForm": "Completing task one",
                },
                {
                    "content": "Task two",
                    "status": "in_progress",
                    "activeForm": "Doing task two",
                },
                {
                    "content": "Task three",
                    "status": "pending",
                    "activeForm": "Starting task three",
                },
            ],
            status="updated",
        )
        display.handle_event(event)

        output = buf.getvalue()
        assert "Task one" in output
        assert "Task two" in output
        assert "Task three" in output
        # Progress bar should show completed/total ratio (1 completed out of 3)
        assert "1/3" in output


# ---------------------------------------------------------------------------
# Test 12: test_todo_update_empty
# ---------------------------------------------------------------------------


class TestTodoUpdateEmpty:
    def test_todo_update_empty(self) -> None:
        """TodoUpdateEvent with empty todos list should not crash."""
        from amplifier_ipc.cli.streaming import StreamingDisplay
        from amplifier_ipc.host.events import TodoUpdateEvent

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = TodoUpdateEvent(todos=[], status="listed")
        # Should not raise any exception
        display.handle_event(event)


# ---------------------------------------------------------------------------
# Test 13: test_thinking_block_has_borders
# ---------------------------------------------------------------------------


class TestThinkingBlockHasBorders:
    def test_thinking_block_has_borders(self) -> None:
        """StreamContentBlockStart(thinking) -> StreamThinkingEvent -> StreamContentBlockEnd(thinking)
        should render the thinking text between double-line borders with a header."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console, show_thinking=True)

        display.handle_event(StreamContentBlockStartEvent(block_type="thinking"))
        display.handle_event(
            StreamThinkingEvent(thinking="Let me think about this carefully.")
        )
        display.handle_event(StreamContentBlockEndEvent(block_type="thinking"))

        output = buf.getvalue()
        # Thinking text must appear
        assert "Let me think about this carefully." in output
        # Header or double-line border characters must be present
        assert (
            "Thinking" in output or "\u2550" in output
        )  # ═ (U+2550 double horizontal)


class TestThinkingBlockHiddenWhenDisabled:
    def test_thinking_block_hidden_when_disabled(self) -> None:
        """When show_thinking=False, borders and thinking text should NOT be rendered."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console, show_thinking=False)

        display.handle_event(StreamContentBlockStartEvent(block_type="thinking"))
        display.handle_event(StreamThinkingEvent(thinking="Secret thoughts"))
        display.handle_event(StreamContentBlockEndEvent(block_type="thinking"))

        output = buf.getvalue()
        assert "Secret thoughts" not in output
        # No border characters either
        assert "\u2550" not in output  # ═


class TestNonThinkingBlockIgnored:
    def test_non_thinking_block_ignored(self) -> None:
        """StreamContentBlockStartEvent with a non-thinking block_type should not set thinking state."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console, show_thinking=True)

        display.handle_event(StreamContentBlockStartEvent(block_type="text"))
        display.handle_event(StreamContentBlockEndEvent(block_type="text"))

        output = buf.getvalue()
        # No border characters should be printed for a non-thinking block
        assert "\u2550" not in output  # ═


# ---------------------------------------------------------------------------
# Test 15 (original 13 renamed): test_todo_update_condensed_mode_line_width
# ---------------------------------------------------------------------------


class TestTodoUpdateCondensedModeLineWidth:
    def test_todo_update_condensed_mode_line_width(self) -> None:
        """Condensed-mode summary line must have the same char width as the border lines."""
        from amplifier_ipc.cli.streaming import StreamingDisplay
        from amplifier_ipc.host.events import TodoUpdateEvent

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        # 8 todos triggers condensed mode (threshold is 7)
        todos = [
            {"content": f"Task {i}", "status": "pending", "activeForm": f"Doing {i}"}
            for i in range(8)
        ]
        todos[0]["status"] = "completed"

        event = TodoUpdateEvent(todos=todos, status="updated")
        display.handle_event(event)

        lines = buf.getvalue().splitlines()
        # Find border lines (start with ┌ or └)
        border_lines = [ln for ln in lines if ln.startswith("┌") or ln.startswith("└")]
        assert border_lines, "Expected box border lines in output"
        border_width = len(border_lines[0])

        # Find the condensed summary line (starts with │ and contains "completed")
        summary_lines = [ln for ln in lines if ln.startswith("│") and "completed" in ln]
        assert summary_lines, "Expected a condensed summary line"
        assert len(summary_lines[0]) == border_width, (
            f"Condensed summary line width {len(summary_lines[0])} "
            f"!= border width {border_width}"
        )


# ---------------------------------------------------------------------------
# Child session event tests
# ---------------------------------------------------------------------------


class TestChildSessionStartEvent:
    def test_child_session_start_renders_agent_name(self) -> None:
        """ChildSessionStartEvent should print the agent name with gear icon and delegate header."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = ChildSessionStartEvent(agent_name="explorer", session_id="child-123")
        display.handle_event(event)

        output = buf.getvalue()
        assert "explorer" in output
        assert "\u2699" in output  # ⚙ gear icon


class TestChildSessionEventUnwraps:
    def test_child_session_event_unwraps_inner(self) -> None:
        """ChildSessionEvent should unwrap and render the inner event."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        inner = StreamTokenEvent(token="Hello from child")
        event = ChildSessionEvent(depth=1, inner=inner)
        display.handle_event(event)

        output = buf.getvalue()
        assert "Hello from child" in output


class TestChildSessionEventNoneInner:
    def test_child_session_event_none_inner(self) -> None:
        """ChildSessionEvent with None inner should not crash."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = ChildSessionEvent(depth=1, inner=None)
        display.handle_event(event)  # Should not raise


class TestErrorEventShowsCrossIcon:
    def test_error_event_shows_cross(self) -> None:
        """ErrorEvent should show the cross icon."""
        from amplifier_ipc.cli.streaming import StreamingDisplay
        from amplifier_ipc.host.events import ErrorEvent

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = ErrorEvent(message="Something went wrong")
        display.handle_event(event)

        output = buf.getvalue()
        assert "Something went wrong" in output
        assert "\u2717" in output  # ✗ cross icon


class TestToolCallStartShowsGearIcon:
    def test_tool_call_start_shows_gear(self) -> None:
        """StreamToolCallStartEvent should show the gear icon."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = StreamToolCallStartEvent(tool_name="bash")
        display.handle_event(event)

        output = buf.getvalue()
        assert "bash" in output
        assert "\u2699" in output  # ⚙ gear icon


# ---------------------------------------------------------------------------
# New child session rendering tests (task-12)
# ---------------------------------------------------------------------------


class TestChildSessionStartRendersDelegateHeader:
    def test_child_session_start_renders_delegate_header(self) -> None:
        """ChildSessionStartEvent should render gear icon and 'delegate' header with agent name."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = ChildSessionStartEvent(
            agent_name="explorer", session_id="child-123", depth=1
        )
        display.handle_event(event)

        output = buf.getvalue()
        assert "explorer" in output
        assert "delegate" in output and "\u2699" in output  # ⚙ gear icon


class TestChildSessionEventIndentsInner:
    def test_child_session_event_indents_inner(self) -> None:
        """ChildSessionEvent at depth=1 wrapping ToolCallEvent should indent output with 4 spaces."""
        from amplifier_ipc.cli.streaming import StreamingDisplay
        from amplifier_ipc.host.events import ToolCallEvent

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        inner = ToolCallEvent(tool_name="read_file", arguments={"path": "/some/file"})
        event = ChildSessionEvent(depth=1, inner=inner)
        display.handle_event(event)

        output = buf.getvalue()
        assert "read_file" in output
        # At least one non-empty line should be indented with 4 spaces
        non_empty_lines = [ln for ln in output.splitlines() if ln.strip()]
        assert any(ln.startswith("    ") for ln in non_empty_lines)


class TestChildSessionEventDepth2:
    def test_child_session_event_depth_2(self) -> None:
        """ChildSessionEvent at depth=2 should indent output with 8 spaces."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        inner = StreamTokenEvent(token="nested content")
        event = ChildSessionEvent(depth=2, inner=inner)
        display.handle_event(event)

        output = buf.getvalue()
        assert "nested content" in output
        # At least one non-empty line should be indented with 8 spaces (depth=2)
        non_empty_lines = [ln for ln in output.splitlines() if ln.strip()]
        assert any(ln.startswith("        ") for ln in non_empty_lines)


class TestChildSessionEndIsSilent:
    def test_child_session_end_is_silent(self) -> None:
        """ChildSessionEndEvent should produce no visible output."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = ChildSessionEndEvent(session_id="child-123")
        display.handle_event(event)

        output = buf.getvalue()
        assert output.strip() == ""
