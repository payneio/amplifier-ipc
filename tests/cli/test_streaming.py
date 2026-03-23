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
