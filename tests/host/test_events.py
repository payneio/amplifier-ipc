"""Tests for HostEvent model hierarchy."""

from __future__ import annotations

from pydantic import BaseModel

from amplifier_ipc.host.events import (
    ApprovalRequestEvent,
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


def test_host_event_is_pydantic_base_model() -> None:
    """HostEvent and all subclasses are Pydantic BaseModel instances."""
    event = HostEvent()
    assert isinstance(event, BaseModel)
    assert isinstance(StreamTokenEvent(token="x"), BaseModel)
    assert isinstance(ApprovalRequestEvent(), BaseModel)


def test_host_event_is_base() -> None:
    """HostEvent is the base class and can be instantiated."""
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


# ---------------------------------------------------------------------------
# New event types
# ---------------------------------------------------------------------------


def test_tool_call_event_defaults() -> None:
    """ToolCallEvent has default empty tool_name and empty arguments dict."""
    event = ToolCallEvent()
    assert isinstance(event, HostEvent)
    assert event.tool_name == ""
    assert event.arguments == {}


def test_tool_call_event_construction() -> None:
    """ToolCallEvent stores tool_name and arguments."""
    event = ToolCallEvent(tool_name="bash", arguments={"command": "ls"})
    assert isinstance(event, HostEvent)
    assert event.tool_name == "bash"
    assert event.arguments == {"command": "ls"}


def test_tool_result_event_defaults() -> None:
    """ToolResultEvent has default empty tool_name, success=True, and empty output."""
    event = ToolResultEvent()
    assert isinstance(event, HostEvent)
    assert event.tool_name == ""
    assert event.success is True
    assert event.output == ""


def test_tool_result_event_construction() -> None:
    """ToolResultEvent stores tool_name, success, and output."""
    event = ToolResultEvent(tool_name="bash", success=False, output="error text")
    assert isinstance(event, HostEvent)
    assert event.tool_name == "bash"
    assert event.success is False
    assert event.output == "error text"


def test_todo_update_event_defaults() -> None:
    """TodoUpdateEvent has default empty todos list and empty status string."""
    event = TodoUpdateEvent()
    assert isinstance(event, HostEvent)
    assert event.todos == []
    assert event.status == ""


def test_todo_update_event_construction() -> None:
    """TodoUpdateEvent stores todos and status."""
    todos = [{"content": "Do thing", "status": "pending"}]
    event = TodoUpdateEvent(todos=todos, status="in_progress")
    assert isinstance(event, HostEvent)
    assert event.todos == todos
    assert event.status == "in_progress"


def test_child_session_start_event_defaults() -> None:
    """ChildSessionStartEvent has expected defaults."""
    event = ChildSessionStartEvent()
    assert isinstance(event, HostEvent)
    assert event.agent_name == ""
    assert event.session_id == ""
    assert event.depth == 1


def test_child_session_end_event_defaults() -> None:
    """ChildSessionEndEvent has expected defaults."""
    event = ChildSessionEndEvent()
    assert isinstance(event, HostEvent)
    assert event.session_id == ""
    assert event.depth == 1


def test_child_session_event_defaults() -> None:
    """ChildSessionEvent has expected defaults with inner=None."""
    event = ChildSessionEvent()
    assert isinstance(event, HostEvent)
    assert event.depth == 1
    assert event.inner is None


def test_child_session_event_nested() -> None:
    """ChildSessionEvent can wrap another ChildSessionEvent for recursive depth."""
    inner = ChildSessionEvent(depth=2, inner=ToolCallEvent(tool_name="bash"))
    outer = ChildSessionEvent(depth=1, inner=inner)
    assert isinstance(outer, HostEvent)
    assert outer.depth == 1
    assert isinstance(outer.inner, ChildSessionEvent)
    assert outer.inner.depth == 2
    assert isinstance(outer.inner.inner, ToolCallEvent)
