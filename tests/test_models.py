"""Tests for Pydantic v2 wire-format data models."""

from __future__ import annotations

import json

from amplifier_ipc_protocol.models import (
    ChatRequest,
    ChatResponse,
    HookAction,
    HookResult,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolCallBlock,
    ToolResult,
    ToolSpec,
    Usage,
)

# ---------------------------------------------------------------------------
# ToolCall tests (3)
# ---------------------------------------------------------------------------


def test_tool_call_basic_construction():
    """ToolCall constructs with id, name, arguments."""
    tc = ToolCall(id="call-1", name="my_tool", arguments={"x": 1})
    assert tc.id == "call-1"
    assert tc.name == "my_tool"
    assert tc.arguments == {"x": 1}


def test_tool_call_name_alias():
    """ToolCall accepts 'tool' as alias for 'name'."""
    tc = ToolCall(id="call-2", tool="aliased_tool", arguments={})  # type: ignore[call-arg]
    assert tc.name == "aliased_tool"


def test_tool_call_json_roundtrip():
    """ToolCall round-trips through model_dump(mode='json') -> json serialization."""
    tc = ToolCall(id="call-3", name="round_trip", arguments={"a": "b"})
    dumped = tc.model_dump(mode="json")
    serialized = json.dumps(dumped)
    loaded_dict = json.loads(serialized)
    tc2 = ToolCall.model_validate(loaded_dict)
    assert tc2.id == tc.id
    assert tc2.name == tc.name
    assert tc2.arguments == tc.arguments


# ---------------------------------------------------------------------------
# Message tests (5)
# ---------------------------------------------------------------------------


def test_message_basic_construction():
    """Message constructs with role and string content."""
    msg = Message(role="user", content="Hello!")
    assert msg.role == "user"
    assert msg.content == "Hello!"


def test_message_defaults():
    """Message optional fields default to None."""
    msg = Message(role="assistant")
    assert msg.content is None
    assert msg.tool_calls is None
    assert msg.tool_call_id is None
    assert msg.name is None
    assert msg.metadata is None
    assert msg.thinking_block is None


def test_message_with_tool_calls():
    """Message supports tool_calls list."""
    tc = ToolCall(id="c1", name="fn", arguments={"k": "v"})
    msg = Message(role="assistant", tool_calls=[tc])
    assert msg.tool_calls is not None
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0].name == "fn"


def test_message_extra_fields_allowed():
    """Message allows extra fields (extra='allow')."""
    msg = Message(role="user", content="Hi", custom_field="extra_value")  # type: ignore[call-arg]
    assert msg.custom_field == "extra_value"  # type: ignore[attr-defined]


def test_message_json_roundtrip():
    """Message round-trips through JSON cleanly."""
    msg = Message(
        role="user",
        content="test",
        metadata={"key": "val"},
    )
    dumped = msg.model_dump(mode="json")
    serialized = json.dumps(dumped)
    loaded = json.loads(serialized)
    msg2 = Message.model_validate(loaded)
    assert msg2.role == msg.role
    assert msg2.content == msg.content
    assert msg2.metadata == msg.metadata


# ---------------------------------------------------------------------------
# ToolSpec tests (2)
# ---------------------------------------------------------------------------


def test_tool_spec_basic_construction():
    """ToolSpec constructs with name, description, parameters."""
    spec = ToolSpec(
        name="search",
        description="Search the web",
        parameters={"type": "object", "properties": {}},
    )
    assert spec.name == "search"
    assert spec.description == "Search the web"
    assert spec.parameters == {"type": "object", "properties": {}}


def test_tool_spec_parameters_default():
    """ToolSpec parameters defaults to empty dict."""
    spec = ToolSpec(name="noop", description="Does nothing")
    assert spec.parameters == {}


# ---------------------------------------------------------------------------
# ToolResult tests (5 + 1 list coverage)
# ---------------------------------------------------------------------------


def test_tool_result_defaults():
    """ToolResult defaults: success=True, output=None, error=None."""
    result = ToolResult()
    assert result.success is True
    assert result.output is None
    assert result.error is None


def test_tool_result_get_serialized_output_dict():
    """get_serialized_output() returns json.dumps for dict output."""
    result = ToolResult(output={"key": "value", "num": 42})
    serialized = result.get_serialized_output()
    assert serialized == json.dumps({"key": "value", "num": 42})


def test_tool_result_get_serialized_output_list():
    """get_serialized_output() returns json.dumps for list output."""
    result = ToolResult(output=["a", "b"])
    assert result.get_serialized_output() == json.dumps(["a", "b"])


def test_tool_result_get_serialized_output_str():
    """get_serialized_output() returns str() for non-dict/list output."""
    result = ToolResult(output="plain text result")
    assert result.get_serialized_output() == "plain text result"


def test_tool_result_get_serialized_output_none():
    """get_serialized_output() returns '' when output is None."""
    result = ToolResult(output=None)
    assert result.get_serialized_output() == ""


def test_tool_result_extra_fields_allowed():
    """ToolResult allows extra fields (extra='allow')."""
    result = ToolResult(success=True, output="ok", extra_meta="some_value")  # type: ignore[call-arg]
    assert result.extra_meta == "some_value"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# HookAction / HookResult tests (5)
# ---------------------------------------------------------------------------


def test_hook_action_all_values():
    """HookAction has exactly 5 expected values."""
    assert HookAction.CONTINUE == "CONTINUE"
    assert HookAction.DENY == "DENY"
    assert HookAction.MODIFY == "MODIFY"
    assert HookAction.INJECT_CONTEXT == "INJECT_CONTEXT"
    assert HookAction.ASK_USER == "ASK_USER"
    assert len(HookAction) == 5


def test_hook_result_defaults_to_continue():
    """HookResult defaults action to CONTINUE."""
    hr = HookResult()
    assert hr.action == HookAction.CONTINUE
    assert hr.injected_messages == []
    assert hr.ephemeral is False
    assert hr.approval_timeout == 300.0
    assert hr.approval_default == "deny"


def test_hook_result_with_message():
    """HookResult can hold a Message object."""
    msg = Message(role="user", content="Inject this")
    hr = HookResult(action=HookAction.INJECT_CONTEXT, message=msg)
    assert hr.action == HookAction.INJECT_CONTEXT
    assert hr.message is not None
    assert hr.message.content == "Inject this"


def test_hook_result_injected_messages():
    """HookResult supports injected_messages list."""
    msgs = [Message(role="user", content=f"msg {i}") for i in range(3)]
    hr = HookResult(injected_messages=msgs)
    assert len(hr.injected_messages) == 3


def test_hook_result_json_roundtrip():
    """HookResult round-trips through JSON cleanly."""
    hr = HookResult(
        action=HookAction.DENY,
        reason="not allowed",
        suppress_output=True,
    )
    dumped = hr.model_dump(mode="json")
    serialized = json.dumps(dumped)
    loaded = json.loads(serialized)
    hr2 = HookResult.model_validate(loaded)
    assert hr2.action == HookAction.DENY
    assert hr2.reason == "not allowed"
    assert hr2.suppress_output is True


# ---------------------------------------------------------------------------
# ChatRequest / ChatResponse tests (5)
# ---------------------------------------------------------------------------


def test_chat_request_basic():
    """ChatRequest constructs with messages list."""
    msgs = [Message(role="user", content="Hello")]
    req = ChatRequest(messages=msgs)
    assert len(req.messages) == 1
    assert req.tools is None
    assert req.system is None


def test_chat_request_full():
    """ChatRequest with all fields set."""
    msgs = [Message(role="user", content="Search for cats")]
    tools = [ToolSpec(name="search", description="Web search")]
    req = ChatRequest(
        messages=msgs,
        tools=tools,
        system="You are a helpful assistant.",
        reasoning_effort="high",
        max_output_tokens=1024,
        temperature=0.7,
    )
    assert req.system == "You are a helpful assistant."
    assert req.tools is not None
    assert len(req.tools) == 1
    assert req.max_output_tokens == 1024


def test_chat_response_basic():
    """ChatResponse constructs with content."""
    resp = ChatResponse(content="Hello, world!")
    assert resp.content == "Hello, world!"
    assert resp.tool_calls is None
    assert resp.finish_reason is None


def test_chat_response_with_tool_calls():
    """ChatResponse can contain tool_calls."""
    tc = ToolCall(id="c1", name="search", arguments={"q": "cats"})
    resp = ChatResponse(tool_calls=[tc])
    assert resp.tool_calls is not None
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "search"


def test_chat_request_json_roundtrip():
    """ChatRequest round-trips through JSON cleanly."""
    req = ChatRequest(
        messages=[Message(role="user", content="Hi")],
        system="Be helpful",
        temperature=0.5,
    )
    dumped = req.model_dump(mode="json")
    serialized = json.dumps(dumped)
    loaded = json.loads(serialized)
    req2 = ChatRequest.model_validate(loaded)
    assert req2.system == req.system
    assert req2.temperature == req.temperature
    assert req2.messages[0].content == "Hi"


# ---------------------------------------------------------------------------
# Content block tests (3)
# ---------------------------------------------------------------------------


def test_text_block():
    """TextBlock constructs with type='text' and text field."""
    block = TextBlock(text="Hello from text block")
    assert block.type == "text"
    assert block.text == "Hello from text block"
    assert block.visibility is None


def test_thinking_block():
    """ThinkingBlock constructs with type='thinking'."""
    block = ThinkingBlock(thinking="I am reasoning...", signature="sig-123")
    assert block.type == "thinking"
    assert block.thinking == "I am reasoning..."
    assert block.signature == "sig-123"
    assert block.content is None


def test_tool_call_block():
    """ToolCallBlock constructs with type='tool_call'."""
    block = ToolCallBlock(id="b1", name="my_fn", input={"arg": "val"})
    assert block.type == "tool_call"
    assert block.id == "b1"
    assert block.name == "my_fn"
    assert block.input == {"arg": "val"}


# ---------------------------------------------------------------------------
# Usage tests (2)
# ---------------------------------------------------------------------------


def test_usage_defaults():
    """Usage defaults all token counts to 0."""
    usage = Usage()
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.total_tokens == 0
    assert usage.reasoning_tokens is None
    assert usage.cache_read_tokens is None
    assert usage.cache_write_tokens is None


def test_usage_json_roundtrip():
    """Usage round-trips through JSON cleanly."""
    usage = Usage(
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        reasoning_tokens=20,
    )
    dumped = usage.model_dump(mode="json")
    serialized = json.dumps(dumped)
    loaded = json.loads(serialized)
    usage2 = Usage.model_validate(loaded)
    assert usage2.input_tokens == 100
    assert usage2.output_tokens == 50
    assert usage2.total_tokens == 150
    assert usage2.reasoning_tokens == 20
