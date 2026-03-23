"""Tests for StreamingDisplay class in streaming.py."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from amplifier_ipc.host.events import (
    CompleteEvent,
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
