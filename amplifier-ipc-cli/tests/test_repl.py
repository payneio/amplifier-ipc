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


# ---------------------------------------------------------------------------
# Test: ApprovalRequestEvent handling calls host.send_approval
# ---------------------------------------------------------------------------


class TestHandleHostEventApprovalCallsSendApproval:
    def test_handle_host_event_approval_calls_send_approval(self) -> None:
        """ApprovalRequestEvent handling in interactive_repl calls host.send_approval."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from amplifier_ipc_host.events import ApprovalRequestEvent

        from amplifier_ipc_cli.repl import interactive_repl

        event = ApprovalRequestEvent(params={})

        host = MagicMock()

        async def mock_run(message: str):  # type: ignore[no-untyped-def]
            yield event

        host.run = mock_run
        host.send_approval = MagicMock()

        call_count = 0

        async def mock_prompt_async(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "hello"
            raise EOFError()

        mock_session = MagicMock()
        mock_session.prompt_async = mock_prompt_async

        with patch("amplifier_ipc_cli.repl.CLIApprovalHandler") as mock_handler_class:
            mock_handler = MagicMock()
            mock_handler.handle_approval = AsyncMock(return_value=True)
            mock_handler_class.return_value = mock_handler

            with patch(
                "amplifier_ipc_cli.repl._create_prompt_session",
                return_value=mock_session,
            ):
                console = MagicMock()
                asyncio.run(interactive_repl(host, console=console))

        host.send_approval.assert_called_once_with(True)
