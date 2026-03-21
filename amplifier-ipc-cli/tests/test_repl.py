"""Tests for the REPL module: handle_host_event and related functions."""

from __future__ import annotations

import sys
from io import StringIO
from unittest.mock import patch

from amplifier_ipc_host.events import (
    CompleteEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
    ErrorEvent,
)


# ---------------------------------------------------------------------------
# Test 1: test_handle_stream_token
# ---------------------------------------------------------------------------


class TestHandleStreamToken:
    def test_handle_stream_token(self) -> None:
        """StreamTokenEvent should write the token text to stdout."""
        from amplifier_ipc_cli.repl import handle_host_event

        event = StreamTokenEvent(token="Hello, world!")

        captured = StringIO()
        with patch.object(sys, "stdout", captured):
            handle_host_event(event)

        assert captured.getvalue() == "Hello, world!"


# ---------------------------------------------------------------------------
# Test 2: test_handle_complete_event
# ---------------------------------------------------------------------------


class TestHandleCompleteEvent:
    def test_handle_complete_event(self) -> None:
        """CompleteEvent should store the result in the state dict."""
        from amplifier_ipc_cli.repl import handle_host_event

        event = CompleteEvent(result="Final answer")
        state: dict = {}

        handle_host_event(event, state=state)

        assert state.get("response") == "Final answer"

    def test_handle_complete_event_writes_newline(self) -> None:
        """CompleteEvent should also write a newline to stdout."""
        from amplifier_ipc_cli.repl import handle_host_event

        event = CompleteEvent(result="Done")
        state: dict = {}

        captured = StringIO()
        with patch.object(sys, "stdout", captured):
            handle_host_event(event, state=state)

        assert "\n" in captured.getvalue()


# ---------------------------------------------------------------------------
# Test 3: test_handle_tool_call_start
# ---------------------------------------------------------------------------


class TestHandleToolCallStart:
    def test_handle_tool_call_start_no_error(self) -> None:
        """StreamToolCallStartEvent should be handled without raising an error."""
        from amplifier_ipc_cli.repl import handle_host_event

        event = StreamToolCallStartEvent(tool_name="my_tool")

        # Should not raise
        handle_host_event(event)


# ---------------------------------------------------------------------------
# Additional tests: ErrorEvent and StreamThinkingEvent coverage
# ---------------------------------------------------------------------------


class TestHandleStreamThinking:
    def test_handle_stream_thinking_no_error(self) -> None:
        """StreamThinkingEvent should be handled without raising an error."""
        from amplifier_ipc_cli.repl import handle_host_event

        event = StreamThinkingEvent(thinking="Some deep thoughts")

        # Should not raise
        handle_host_event(event)


class TestHandleErrorEvent:
    def test_handle_error_event_no_error(self) -> None:
        """ErrorEvent should be handled without raising an error."""
        from amplifier_ipc_cli.repl import handle_host_event

        event = ErrorEvent(message="Something went wrong")

        # Should not raise
        handle_host_event(event)


# ---------------------------------------------------------------------------
# Test: interactive_repl function exists
# ---------------------------------------------------------------------------


class TestInteractiveReplExists:
    def test_interactive_repl_is_callable(self) -> None:
        """interactive_repl should be importable and callable."""
        from amplifier_ipc_cli.repl import interactive_repl

        assert callable(interactive_repl)
