"""Tests for HostEvent dataclass hierarchy."""

from __future__ import annotations

from amplifier_ipc.host.events import (
    ApprovalRequestEvent,
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamContentBlockEndEvent,
    StreamContentBlockStartEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)


def test_host_event_is_base() -> None:
    """HostEvent is the base dataclass and can be instantiated."""
    event = HostEvent()
    assert isinstance(event, HostEvent)


def test_stream_token_event() -> None:
    """StreamTokenEvent holds a token string and is a HostEvent subclass."""
    event = StreamTokenEvent(token="hello")
    assert isinstance(event, HostEvent)
    assert event.token == "hello"


def test_stream_thinking_event() -> None:
    """StreamThinkingEvent holds a thinking string and is a HostEvent subclass."""
    event = StreamThinkingEvent(thinking="some thought")
    assert isinstance(event, HostEvent)
    assert event.thinking == "some thought"


def test_stream_tool_call_start_event() -> None:
    """StreamToolCallStartEvent holds a tool_name string and is a HostEvent subclass."""
    event = StreamToolCallStartEvent(tool_name="bash")
    assert isinstance(event, HostEvent)
    assert event.tool_name == "bash"


def test_approval_request_event() -> None:
    """ApprovalRequestEvent holds a params dict and is a HostEvent subclass."""
    params = {"message": "Allow access?", "options": ["yes", "no"]}
    event = ApprovalRequestEvent(params=params)
    assert isinstance(event, HostEvent)
    assert event.params == params


def test_error_event() -> None:
    """ErrorEvent holds an error message string and is a HostEvent subclass."""
    event = ErrorEvent(message="Something went wrong")
    assert isinstance(event, HostEvent)
    assert event.message == "Something went wrong"


def test_stream_content_block_start_event() -> None:
    """StreamContentBlockStartEvent holds block_type and index and is a HostEvent subclass."""
    event = StreamContentBlockStartEvent(block_type="text", index=0)
    assert isinstance(event, HostEvent)
    assert event.block_type == "text"
    assert event.index == 0


def test_stream_content_block_end_event() -> None:
    """StreamContentBlockEndEvent holds block_type and index and is a HostEvent subclass."""
    event = StreamContentBlockEndEvent(block_type="text", index=0)
    assert isinstance(event, HostEvent)
    assert event.block_type == "text"
    assert event.index == 0


def test_complete_event() -> None:
    """CompleteEvent holds the final result string and is a HostEvent subclass."""
    event = CompleteEvent(result="Final answer here")
    assert isinstance(event, HostEvent)
    assert event.result == "Final answer here"
