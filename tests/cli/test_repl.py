"""Tests for the REPL module: handle_host_event, CancellationState, and interactive_repl."""

from __future__ import annotations

import asyncio
import sys
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

from amplifier_ipc.cli.repl import CancellationState
from amplifier_ipc.host.events import (
    ChildSessionEndEvent,
    ChildSessionEvent,
    ChildSessionStartEvent,
    CompleteEvent,
    ErrorEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
    TodoUpdateEvent,
    ToolCallEvent,
    ToolResultEvent,
)

# ---------------------------------------------------------------------------
# Test: ToolCallEvent handling
# ---------------------------------------------------------------------------


class TestHandleToolCallEvent:
    def test_tool_call_event_no_error(self) -> None:
        """ToolCallEvent should be handled without raising an error."""
        from amplifier_ipc.cli.repl import handle_host_event

        event = ToolCallEvent(tool_name="bash", arguments={"command": "ls -la"})

        # Should not raise
        handle_host_event(event)

    def test_tool_call_event_output_contains_tool_name(self) -> None:
        """ToolCallEvent output should contain the tool name."""
        from amplifier_ipc.cli.repl import handle_host_event

        event = ToolCallEvent(tool_name="bash", arguments={"command": "ls -la"})

        captured = StringIO()
        with patch("click.echo", side_effect=lambda msg, **kw: captured.write(str(msg) + "\n")):
            handle_host_event(event)

        assert "bash" in captured.getvalue()


# ---------------------------------------------------------------------------
# Test: ToolResultEvent handling
# ---------------------------------------------------------------------------


class TestHandleToolResultEvent:
    def test_tool_result_event_no_error(self) -> None:
        """ToolResultEvent should be handled without raising an error."""
        from amplifier_ipc.cli.repl import handle_host_event

        event = ToolResultEvent(tool_name="bash", success=True, output="file1\nfile2")

        # Should not raise
        handle_host_event(event)

    def test_tool_result_event_failure_no_error(self) -> None:
        """ToolResultEvent with failure should be handled without raising an error."""
        from amplifier_ipc.cli.repl import handle_host_event

        event = ToolResultEvent(tool_name="bash", success=False, output="command not found")

        # Should not raise
        handle_host_event(event)


# ---------------------------------------------------------------------------
# Test: ChildSessionStartEvent handling
# ---------------------------------------------------------------------------


class TestHandleChildSessionStart:
    def test_child_session_start_no_error(self) -> None:
        """ChildSessionStartEvent should be handled without raising an error."""
        from amplifier_ipc.cli.repl import handle_host_event

        event = ChildSessionStartEvent(agent_name="my-agent", session_id="abc123", depth=1)

        # Should not raise
        handle_host_event(event)

    def test_child_session_end_no_error(self) -> None:
        """ChildSessionEndEvent should be handled without raising an error (silent)."""
        from amplifier_ipc.cli.repl import handle_host_event

        event = ChildSessionEndEvent(session_id="abc123", depth=1)

        # Should not raise
        handle_host_event(event)

    def test_child_session_event_no_error(self) -> None:
        """ChildSessionEvent should be handled without raising an error."""
        from amplifier_ipc.cli.repl import handle_host_event

        inner = StreamTokenEvent(token="hello")
        event = ChildSessionEvent(depth=1, inner=inner)

        # Should not raise
        handle_host_event(event)


# ---------------------------------------------------------------------------
# Test: TodoUpdateEvent handling
# ---------------------------------------------------------------------------


class TestHandleTodoUpdateEvent:
    def test_todo_update_event_no_error(self) -> None:
        """TodoUpdateEvent should be handled without raising an error."""
        from amplifier_ipc.cli.repl import handle_host_event

        event = TodoUpdateEvent(
            todos=[
                {"content": "Task 1", "status": "completed"},
                {"content": "Task 2", "status": "in_progress"},
            ]
        )

        # Should not raise
        handle_host_event(event)


# ---------------------------------------------------------------------------
# Test 1: test_handle_stream_token
# ---------------------------------------------------------------------------


class TestHandleStreamToken:
    def test_handle_stream_token(self) -> None:
        """StreamTokenEvent should write the token text to stdout."""
        from amplifier_ipc.cli.repl import handle_host_event

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
        from amplifier_ipc.cli.repl import handle_host_event

        event = CompleteEvent(result="Final answer")
        state: dict = {}

        handle_host_event(event, state=state)

        assert state.get("response") == "Final answer"

    def test_handle_complete_event_writes_newline(self) -> None:
        """CompleteEvent should also write a newline to stdout."""
        from amplifier_ipc.cli.repl import handle_host_event

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
        from amplifier_ipc.cli.repl import handle_host_event

        event = StreamToolCallStartEvent(tool_name="my_tool")

        # Should not raise
        handle_host_event(event)


# ---------------------------------------------------------------------------
# Additional tests: ErrorEvent and StreamThinkingEvent coverage
# ---------------------------------------------------------------------------


class TestHandleStreamThinking:
    def test_handle_stream_thinking_no_error(self) -> None:
        """StreamThinkingEvent should be handled without raising an error."""
        from amplifier_ipc.cli.repl import handle_host_event

        event = StreamThinkingEvent(thinking="Some deep thoughts")

        # Should not raise
        handle_host_event(event)


class TestHandleErrorEvent:
    def test_handle_error_event_no_error(self) -> None:
        """ErrorEvent should be handled without raising an error."""
        from amplifier_ipc.cli.repl import handle_host_event

        event = ErrorEvent(message="Something went wrong")

        # Should not raise
        handle_host_event(event)


# ---------------------------------------------------------------------------
# Test: interactive_repl function exists
# ---------------------------------------------------------------------------


class TestInteractiveReplExists:
    def test_interactive_repl_is_callable(self) -> None:
        """interactive_repl should be importable and callable."""
        from amplifier_ipc.cli.repl import interactive_repl

        assert callable(interactive_repl)


# ---------------------------------------------------------------------------
# Test: ApprovalRequestEvent handling calls host.send_approval
# ---------------------------------------------------------------------------


class TestHandleHostEventApprovalCallsSendApproval:
    def test_handle_host_event_approval_calls_send_approval(self) -> None:
        """ApprovalRequestEvent handling in interactive_repl calls host.send_approval."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from amplifier_ipc.host.events import ApprovalRequestEvent

        from amplifier_ipc.cli.repl import interactive_repl

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

        with patch("amplifier_ipc.cli.repl.CLIApprovalHandler") as mock_handler_class:
            mock_handler = MagicMock()
            mock_handler.handle_approval = AsyncMock(return_value=True)
            mock_handler_class.return_value = mock_handler

            with patch(
                "amplifier_ipc.cli.repl._create_prompt_session",
                return_value=mock_session,
            ):
                console = MagicMock()
                asyncio.run(interactive_repl(host, console=console))

        host.send_approval.assert_called_once_with(True)


# ---------------------------------------------------------------------------
# CancellationState tests
# ---------------------------------------------------------------------------


class TestCancellationState:
    def test_initial_state(self) -> None:
        cs = CancellationState()
        assert cs.is_cancelled is False
        assert cs.is_immediate is False
        assert cs.current_tool is None

    def test_request_graceful(self) -> None:
        cs = CancellationState()
        cs.request_graceful()
        assert cs.is_cancelled is True
        assert cs.is_immediate is False

    def test_request_immediate(self) -> None:
        cs = CancellationState()
        cs.request_graceful()
        cs.request_immediate()
        assert cs.is_cancelled is True
        assert cs.is_immediate is True

    def test_reset(self) -> None:
        cs = CancellationState()
        cs.request_graceful()
        cs.request_immediate()
        cs.current_tool = "bash"
        cs.reset()
        assert cs.is_cancelled is False
        assert cs.is_immediate is False
        assert cs.current_tool is None


# ---------------------------------------------------------------------------
# Ctrl+C at prompt confirms exit
# ---------------------------------------------------------------------------


class TestCtrlCAtPromptConfirmsExit:
    def test_ctrl_c_confirm_no_continues_repl(self) -> None:
        """Ctrl+C at prompt with 'no' to confirm should continue the REPL."""
        from amplifier_ipc.cli.repl import interactive_repl

        call_count = 0

        async def mock_prompt_async(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise KeyboardInterrupt()
            raise EOFError()

        mock_session = MagicMock()
        mock_session.prompt_async = mock_prompt_async

        host = MagicMock()
        host.session_id = None
        console = MagicMock()

        with (
            patch(
                "amplifier_ipc.cli.repl._create_prompt_session",
                return_value=mock_session,
            ),
            patch("amplifier_ipc.cli.repl.click") as mock_click,
        ):
            mock_click.confirm.return_value = False
            asyncio.run(interactive_repl(host, console=console))

        # prompt_async was called twice: first raised KeyboardInterrupt,
        # user said "no" to confirm, second raised EOFError
        assert call_count == 2

    def test_ctrl_c_confirm_yes_exits(self) -> None:
        """Ctrl+C at prompt with 'yes' to confirm should exit the REPL."""
        from amplifier_ipc.cli.repl import interactive_repl

        call_count = 0

        async def mock_prompt_async(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            raise KeyboardInterrupt()

        mock_session = MagicMock()
        mock_session.prompt_async = mock_prompt_async

        host = MagicMock()
        host.session_id = None
        console = MagicMock()

        with (
            patch(
                "amplifier_ipc.cli.repl._create_prompt_session",
                return_value=mock_session,
            ),
            patch("amplifier_ipc.cli.repl.click") as mock_click,
        ):
            mock_click.confirm.return_value = True
            asyncio.run(interactive_repl(host, console=console))

        # Only one prompt_async call — exited after confirm
        assert call_count == 1


# ---------------------------------------------------------------------------
# Exit message shows session ID
# ---------------------------------------------------------------------------


class TestExitMessageShowsSessionId:
    def test_exit_message_includes_session_id(self) -> None:
        """After exiting, the REPL should show the session resume command."""
        from amplifier_ipc.cli.repl import interactive_repl

        async def mock_prompt_async(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise EOFError()

        mock_session = MagicMock()
        mock_session.prompt_async = mock_prompt_async

        host = MagicMock()
        host.session_id = "abc1234567890def"
        console = MagicMock()

        with patch(
            "amplifier_ipc.cli.repl._create_prompt_session",
            return_value=mock_session,
        ):
            asyncio.run(
                interactive_repl(host, agent_name="test-agent", console=console)
            )

        # Check that the exit message was printed with the truncated session ID
        printed_text = " ".join(
            str(call) for call in console.print.call_args_list
        )
        assert "abc12345" in printed_text
        assert "test-agent" in printed_text

    def test_no_exit_message_without_session_id(self) -> None:
        """No resume message should be shown if there's no session_id."""
        from amplifier_ipc.cli.repl import interactive_repl

        async def mock_prompt_async(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise EOFError()

        mock_session = MagicMock()
        mock_session.prompt_async = mock_prompt_async

        host = MagicMock()
        host.session_id = None
        console = MagicMock()

        with patch(
            "amplifier_ipc.cli.repl._create_prompt_session",
            return_value=mock_session,
        ):
            asyncio.run(interactive_repl(host, console=console))

        printed_text = " ".join(
            str(call) for call in console.print.call_args_list
        )
        assert "resume" not in printed_text.lower()


# ---------------------------------------------------------------------------
# Two-stage cancellation during execution
# ---------------------------------------------------------------------------


class TestTwoStageCancellation:
    def test_consume_events_forwards_events(self) -> None:
        """_consume_events should forward all events to the queue."""
        from amplifier_ipc.cli.repl import _consume_events

        events = [
            StreamToolCallStartEvent(tool_name="bash"),
            StreamTokenEvent(token="hello"),
            CompleteEvent(result="done"),
        ]

        host = MagicMock()

        async def mock_run(prompt: str):  # type: ignore[no-untyped-def]
            for e in events:
                yield e

        host.run = mock_run

        queue: asyncio.Queue = asyncio.Queue()
        cs = CancellationState()

        asyncio.run(_consume_events(host, "test", queue, cs))

        collected = []
        while not queue.empty():
            collected.append(queue.get_nowait())

        # 3 events + None sentinel
        assert len(collected) == 4
        assert collected[-1] is None
        assert cs.current_tool == "bash"

    def test_consume_events_sentinel_on_cancel(self) -> None:
        """_consume_events should put None sentinel even when cancelled."""
        from amplifier_ipc.cli.repl import _consume_events

        host = MagicMock()

        async def mock_run(prompt: str):  # type: ignore[no-untyped-def]
            await asyncio.sleep(10)  # Block forever
            yield  # Make it a generator  # pragma: no cover

        host.run = mock_run

        queue: asyncio.Queue = asyncio.Queue()
        cs = CancellationState()

        async def run_and_cancel() -> None:
            task = asyncio.create_task(_consume_events(host, "test", queue, cs))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_and_cancel())

        # Sentinel should still be in the queue
        assert not queue.empty()
        assert queue.get_nowait() is None
