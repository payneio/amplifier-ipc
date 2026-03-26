"""Tests for StreamingOrchestrator — discovery, IPC call routing, DENY handling."""

from __future__ import annotations

from typing import Any

import pytest
from amplifier_ipc.protocol.discovery import scan_package


# ---------------------------------------------------------------------------
# MockClient — records all requests and notifications for assertions
# ---------------------------------------------------------------------------


class Sequence:
    """Wrap a sequence of per-call responses so MockClient cycles through them."""

    def __init__(self, *responses: Any) -> None:
        self.responses = responses


class MockClient:
    """Mock IPC client that records calls and returns pre-configured responses.

    Use ``Sequence(r1, r2, ...)`` when a method should return different values
    on successive calls.  Plain values (including ``[]``) are returned as-is
    every time they are requested.

    ``call_log`` records all requests and notifications in chronological order
    as ``("request"|"notification", method, params)`` tuples.
    """

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.requests: list[tuple[str, Any]] = []
        self.notifications: list[tuple[str, Any]] = []
        self.call_log: list[tuple[str, str, Any]] = []
        self._responses: dict[str, Any] = responses or {}
        self._indices: dict[str, int] = {}

    async def request(self, method: str, params: Any = None) -> Any:
        self.requests.append((method, params))
        self.call_log.append(("request", method, params))
        if method not in self._responses:
            return None
        resp = self._responses[method]
        # Only cycle through responses when explicitly wrapped with Sequence
        if isinstance(resp, Sequence):
            idx = self._indices.get(method, 0)
            self._indices[method] = idx + 1
            items = resp.responses
            return items[idx] if idx < len(items) else items[-1]
        return resp

    async def send_notification(self, method: str, params: Any = None) -> None:
        self.notifications.append((method, params))
        self.call_log.append(("notification", method, params))


# ---------------------------------------------------------------------------
# Helpers for building mock responses
# ---------------------------------------------------------------------------


def hook_continue(**kwargs: Any) -> dict[str, Any]:
    return {"action": "CONTINUE", "reason": None, **kwargs}


def hook_deny(reason: str = "Not allowed") -> dict[str, Any]:
    return {"action": "DENY", "reason": reason}


def chat_response(text: str, tool_calls: list | None = None) -> dict[str, Any]:
    return {
        "content": text,
        "text": text,
        "tool_calls": tool_calls,
        "usage": None,
        "finish_reason": None,
    }


def tool_result_ok(output: str = "tool output") -> dict[str, Any]:
    return {"success": True, "output": output, "error": None}


# ---------------------------------------------------------------------------
# Test 1: Discovery
# ---------------------------------------------------------------------------


def test_orchestrator_discovered() -> None:
    """'streaming' orchestrator must be found in orchestrators by scan_package."""
    components = scan_package("amplifier_foundation")
    assert "orchestrator" in components, "scan_package must return 'orchestrator' key"
    names = [o.name for o in components["orchestrator"]]
    assert "streaming" in names, (
        f"'streaming' not found in orchestrators; found: {names}"
    )


# ---------------------------------------------------------------------------
# Test 2: Simple response — correct IPC calls made
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_execute_simple_response() -> None:
    """Simple prompt → hook_emit + context_add_message + provider_complete called."""
    # Import is deferred to keep it out of the test_orchestrator_discovered scope,
    # which must validate discovery before the class is imported into this module.
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": chat_response("Hello!"),
        }
    )

    result = await orch.execute("Hi", {}, client)

    # Verify response text returned
    assert result == "Hello!"

    # Verify hook_emit called at least twice (prompt:submit + orchestrator:complete)
    hook_calls = [m for m, _ in client.requests if m == "request.hook_emit"]
    assert len(hook_calls) >= 2, f"Expected >= 2 hook_emit calls, got {len(hook_calls)}"

    # Verify context_add_message called at least twice (user + assistant)
    add_calls = [m for m, _ in client.requests if m == "request.context_add_message"]
    assert len(add_calls) >= 2, (
        f"Expected >= 2 context_add_message calls, got {len(add_calls)}"
    )

    # Verify provider_complete called exactly once
    provider_calls = [m for m, _ in client.requests if m == "request.provider_complete"]
    assert len(provider_calls) == 1, (
        f"Expected 1 provider_complete call, got {len(provider_calls)}"
    )

    # Verify first add_message was user message
    first_add = next(
        p for m, p in client.requests if m == "request.context_add_message"
    )
    assert first_add["message"]["role"] == "user"
    assert first_add["message"]["content"] == "Hi"

    # Verify stream.token notification sent
    token_notifs = [m for m, _ in client.notifications if m == "stream.token"]
    assert len(token_notifs) >= 1, "Expected at least one stream.token notification"


# ---------------------------------------------------------------------------
# Test 3: Tool call dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_handles_tool_calls() -> None:
    """Tool call in response → tool_execute called with correct name."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    tool_call_response = chat_response(
        text="",
        tool_calls=[{"id": "call_abc", "tool": "my_tool", "arguments": {"x": 42}}],
    )
    final_response = chat_response("All done!")

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": Sequence(tool_call_response, final_response),
            "request.tool_execute": tool_result_ok("tool result"),
        }
    )

    result = await orch.execute("Use my_tool", {}, client)

    assert result == "All done!"

    # Verify tool_execute called with correct name
    tool_calls = [(m, p) for m, p in client.requests if m == "request.tool_execute"]
    assert len(tool_calls) == 1, f"Expected 1 tool_execute call, got {len(tool_calls)}"
    assert tool_calls[0][1]["name"] == "my_tool", (
        f"Expected tool name 'my_tool', got {tool_calls[0][1]['name']!r}"
    )
    assert tool_calls[0][1]["input"] == {"x": 42}


# ---------------------------------------------------------------------------
# Test 4: Hook DENY stops execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_hook_deny_stops_execution() -> None:
    """DENY on prompt:submit must prevent provider_complete from being called."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    client = MockClient(
        responses={
            "request.hook_emit": hook_deny("Blocked by policy"),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": chat_response("Should never reach this"),
        }
    )

    result = await orch.execute("Blocked prompt", {}, client)

    # provider_complete must NOT have been called
    provider_calls = [m for m, _ in client.requests if m == "request.provider_complete"]
    assert len(provider_calls) == 0, (
        f"provider_complete should NOT be called on DENY, but was called {len(provider_calls)} time(s)"
    )

    # Result should convey the denial
    assert (
        "Blocked by policy" in result
        or "denied" in result.lower()
        or "Denied" in result
    )


# ---------------------------------------------------------------------------
# Test 5: stream.thinking notification for thinking blocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_stream_thinking_for_thinking_blocks() -> None:
    """stream.thinking notification sent for each ThinkingBlock in content_blocks, before stream.token."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    response_with_thinking = {
        "content": "Here's my answer.",
        "text": "Here's my answer.",
        "tool_calls": None,
        "usage": None,
        "finish_reason": None,
        "content_blocks": [
            {"type": "thinking", "thinking": "Let me reason about this..."},
            {"type": "text", "text": "Here's my answer."},
        ],
    }

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": response_with_thinking,
        }
    )

    result = await orch.execute("Think about X", {}, client)

    assert result == "Here's my answer."

    # Verify stream.thinking notification was sent
    thinking_notifs = [
        (m, p) for m, p in client.notifications if m == "stream.thinking"
    ]
    assert len(thinking_notifs) == 1, (
        f"Expected 1 stream.thinking notification, got {len(thinking_notifs)}"
    )
    assert thinking_notifs[0][1]["thinking"] == "Let me reason about this..."

    # Verify stream.thinking comes before stream.token in notifications list
    notif_methods = [m for m, _ in client.notifications]
    thinking_idx = notif_methods.index("stream.thinking")
    token_idx = notif_methods.index("stream.token")
    assert thinking_idx < token_idx, (
        f"stream.thinking (idx {thinking_idx}) must come before stream.token (idx {token_idx})"
    )


# ---------------------------------------------------------------------------
# Test 6: stream.tool_call_start notification before tool execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_stream_tool_call_start_before_tool_execution() -> (
    None
):
    """stream.tool_call_start notification sent before tool:pre hook for each tool call."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    tool_call_response = chat_response(
        text="",
        tool_calls=[{"id": "call_abc", "tool": "my_tool", "arguments": {"x": 42}}],
    )
    final_response = chat_response("Done!")

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": Sequence(tool_call_response, final_response),
            "request.tool_execute": tool_result_ok("tool result"),
        }
    )

    result = await orch.execute("Use my_tool", {}, client)

    assert result == "Done!"

    # Verify stream.tool_call_start notification was sent
    tool_start_notifs = [
        (m, p) for m, p in client.notifications if m == "stream.tool_call_start"
    ]
    assert len(tool_start_notifs) == 1, (
        f"Expected 1 stream.tool_call_start notification, got {len(tool_start_notifs)}"
    )
    assert tool_start_notifs[0][1]["tool_name"] == "my_tool"

    # Verify stream.tool_call_start comes before tool:pre hook emit in call_log
    tool_start_idx = next(
        i
        for i, (kind, method, _) in enumerate(client.call_log)
        if kind == "notification" and method == "stream.tool_call_start"
    )
    tool_pre_idx = next(
        i
        for i, (kind, method, params) in enumerate(client.call_log)
        if kind == "request"
        and method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "tool:pre"
    )
    assert tool_start_idx < tool_pre_idx, (
        f"stream.tool_call_start (idx {tool_start_idx}) must come before "
        f"tool:pre hook emit (idx {tool_pre_idx})"
    )


# ---------------------------------------------------------------------------
# Test 7: stream.tool_call notification with tool_name and arguments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_stream_tool_call_notification() -> None:
    """stream.tool_call notification sent with tool_name and arguments before tool execution."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    tool_call_response = chat_response(
        text="",
        tool_calls=[
            {"id": "call_xyz", "tool": "bash", "arguments": {"command": "ls -la"}}
        ],
    )
    final_response = chat_response("Done!")

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": Sequence(tool_call_response, final_response),
            "request.tool_execute": tool_result_ok("file listing"),
        }
    )

    result = await orch.execute("List files", {}, client)

    assert result == "Done!"

    # Verify exactly 1 stream.tool_call notification
    tool_call_notifs = [
        (m, p) for m, p in client.notifications if m == "stream.tool_call"
    ]
    assert len(tool_call_notifs) == 1, (
        f"Expected exactly 1 stream.tool_call notification, got {len(tool_call_notifs)}"
    )

    # Verify the notification contains correct tool_name and arguments
    notif_params = tool_call_notifs[0][1]
    assert notif_params["tool_name"] == "bash", (
        f"Expected tool_name='bash', got {notif_params['tool_name']!r}"
    )
    assert notif_params["arguments"] == {"command": "ls -la"}, (
        f"Expected arguments={{'command': 'ls -la'}}, got {notif_params['arguments']!r}"
    )


# ---------------------------------------------------------------------------
# Test 8: stream.tool_result notification after tool execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_stream_tool_result_notification() -> None:
    """stream.tool_result notification sent after tool execution with correct fields."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    tool_call_response = chat_response(
        text="",
        tool_calls=[
            {"id": "call_hi", "tool": "bash", "arguments": {"command": "echo hi"}}
        ],
    )
    final_response = chat_response("Done!")

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": Sequence(tool_call_response, final_response),
            "request.tool_execute": tool_result_ok("hi"),
        }
    )

    result = await orch.execute("Run bash", {}, client)

    assert result == "Done!"

    # Verify exactly 1 stream.tool_result notification
    tool_result_notifs = [
        (m, p) for m, p in client.notifications if m == "stream.tool_result"
    ]
    assert len(tool_result_notifs) == 1, (
        f"Expected exactly 1 stream.tool_result notification, got {len(tool_result_notifs)}"
    )

    # Verify notification contains correct fields
    notif_params = tool_result_notifs[0][1]
    assert notif_params["tool_name"] == "bash", (
        f"Expected tool_name='bash', got {notif_params['tool_name']!r}"
    )
    assert notif_params["success"] is True, (
        f"Expected success=True, got {notif_params['success']!r}"
    )
    assert "hi" in notif_params["output"], (
        f"Expected 'hi' in output, got {notif_params['output']!r}"
    )


# ---------------------------------------------------------------------------
# Test 9: stream.todo_update notification for todo tool calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_stream_todo_update_for_todo_tool() -> None:
    """stream.todo_update notification sent for 'todo' tool calls returning JSON with 'todos' key."""
    import json

    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    todos_payload = [
        {"content": "Buy milk", "status": "pending", "activeForm": "Buying milk"},
        {
            "content": "Write tests",
            "status": "completed",
            "activeForm": "Writing tests",
        },
    ]
    todo_output = json.dumps({"todos": todos_payload, "status": "updated"})

    tool_call_response = chat_response(
        text="",
        tool_calls=[
            {"id": "call_todo", "tool": "todo", "arguments": {"action": "list"}}
        ],
    )
    final_response = chat_response("Here are your todos!")

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": Sequence(tool_call_response, final_response),
            "request.tool_execute": tool_result_ok(todo_output),
        }
    )

    result = await orch.execute("Show todos", {}, client)

    assert result == "Here are your todos!"

    # Verify exactly 1 stream.todo_update notification was sent
    todo_update_notifs = [
        (m, p) for m, p in client.notifications if m == "stream.todo_update"
    ]
    assert len(todo_update_notifs) == 1, (
        f"Expected exactly 1 stream.todo_update notification, got {len(todo_update_notifs)}"
    )

    # Verify the notification contains 'todos' key
    notif_params = todo_update_notifs[0][1]
    assert "todos" in notif_params, (
        f"Expected 'todos' key in stream.todo_update params, got keys: {list(notif_params.keys())}"
    )
    assert notif_params["todos"] == todos_payload, (
        f"Expected todos={todos_payload!r}, got {notif_params['todos']!r}"
    )


# ---------------------------------------------------------------------------
# Test 10: stream.todo_update NOT sent for non-todo tool calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_does_not_emit_stream_todo_update_for_non_todo_tool() -> (
    None
):
    """stream.todo_update notification is NOT sent for non-todo tool calls."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    tool_call_response = chat_response(
        text="",
        tool_calls=[
            {"id": "call_bash", "tool": "bash", "arguments": {"command": "ls"}}
        ],
    )
    final_response = chat_response("Done!")

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": Sequence(tool_call_response, final_response),
            "request.tool_execute": tool_result_ok("file listing"),
        }
    )

    await orch.execute("List files", {}, client)

    # Verify NO stream.todo_update notification was sent
    todo_update_notifs = [
        (m, p) for m, p in client.notifications if m == "stream.todo_update"
    ]
    assert len(todo_update_notifs) == 0, (
        f"Expected 0 stream.todo_update notifications for non-todo tool, "
        f"got {len(todo_update_notifs)}"
    )


# ---------------------------------------------------------------------------
# Test 11: stream.todo_update NOT sent when todo tool returns JSON without 'todos' key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_does_not_emit_stream_todo_update_when_todos_key_missing() -> (
    None
):
    """stream.todo_update notification is NOT sent when todo tool returns JSON without 'todos' key."""
    import json

    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    # Valid JSON but no 'todos' key
    todo_output = json.dumps({"status": "updated", "count": 0})

    tool_call_response = chat_response(
        text="",
        tool_calls=[
            {"id": "call_todo", "tool": "todo", "arguments": {"action": "list"}}
        ],
    )
    final_response = chat_response("Done!")

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": Sequence(tool_call_response, final_response),
            "request.tool_execute": tool_result_ok(todo_output),
        }
    )

    await orch.execute("List todos", {}, client)

    # Verify NO stream.todo_update notification was sent (no 'todos' key in JSON)
    todo_update_notifs = [
        (m, p) for m, p in client.notifications if m == "stream.todo_update"
    ]
    assert len(todo_update_notifs) == 0, (
        f"Expected 0 stream.todo_update notifications when JSON has no 'todos' key, "
        f"got {len(todo_update_notifs)}"
    )


# ---------------------------------------------------------------------------
# Test 12: stream.todo_update NOT sent when todo tool returns non-JSON output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_does_not_emit_stream_todo_update_for_non_json_output() -> (
    None
):
    """stream.todo_update notification is NOT sent when todo tool returns non-JSON output."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    # Non-JSON output (exercises the except path)
    non_json_output = "Todo list updated successfully."

    tool_call_response = chat_response(
        text="",
        tool_calls=[
            {"id": "call_todo", "tool": "todo", "arguments": {"action": "update"}}
        ],
    )
    final_response = chat_response("Done!")

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": Sequence(tool_call_response, final_response),
            "request.tool_execute": tool_result_ok(non_json_output),
        }
    )

    await orch.execute("Update todos", {}, client)

    # Verify NO stream.todo_update notification was sent (non-JSON output triggers except path)
    todo_update_notifs = [
        (m, p) for m, p in client.notifications if m == "stream.todo_update"
    ]
    assert len(todo_update_notifs) == 0, (
        f"Expected 0 stream.todo_update notifications for non-JSON todo output, "
        f"got {len(todo_update_notifs)}"
    )


# ---------------------------------------------------------------------------
# Test 13: provider:response hook event emitted after successful provider.complete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_provider_response() -> None:
    """provider:response hook event emitted after successful provider.complete with provider name and usage."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    provider_response = {
        "content": "Response from provider.",
        "text": "Response from provider.",
        "tool_calls": None,
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        "finish_reason": None,
    }

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": provider_response,
        }
    )

    result = await orch.execute("Hello", {"provider_name": "anthropic"}, client)

    assert result == "Response from provider."

    # Find all hook_emit calls with event='provider:response'
    provider_response_hook_calls = [
        params
        for method, params in client.requests
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "provider:response"
    ]

    # Verify exactly 1 provider:response hook was emitted
    assert len(provider_response_hook_calls) == 1, (
        f"Expected exactly 1 provider:response hook_emit, got {len(provider_response_hook_calls)}"
    )

    # Verify data payload
    data = provider_response_hook_calls[0].get("data", {})
    assert data.get("provider") == "anthropic", (
        f"Expected provider='anthropic', got {data.get('provider')!r}"
    )
    assert data.get("usage") is not None, "Expected usage to be present in hook data"
    usage = data["usage"]
    # Usage may be a dict or Usage model - check the token counts
    if isinstance(usage, dict):
        assert usage.get("input_tokens") == 10, (
            f"Expected input_tokens=10, got {usage.get('input_tokens')!r}"
        )
        assert usage.get("output_tokens") == 5, (
            f"Expected output_tokens=5, got {usage.get('output_tokens')!r}"
        )
    else:
        assert getattr(usage, "input_tokens", None) == 10, (
            f"Expected input_tokens=10, got {getattr(usage, 'input_tokens', None)!r}"
        )
        assert getattr(usage, "output_tokens", None) == 5, (
            f"Expected output_tokens=5, got {getattr(usage, 'output_tokens', None)!r}"
        )


# ---------------------------------------------------------------------------
# Test 14: CONTENT_BLOCK_START and CONTENT_BLOCK_END constants match expected values
# ---------------------------------------------------------------------------


def test_content_block_constants_match_hook_subscriptions() -> None:
    """CONTENT_BLOCK_START and CONTENT_BLOCK_END must equal 'content_block:start' and 'content_block:end'."""
    from amplifier_ipc_protocol.events import CONTENT_BLOCK_END, CONTENT_BLOCK_START

    assert CONTENT_BLOCK_START == "content_block:start", (
        f"Expected CONTENT_BLOCK_START='content_block:start', got {CONTENT_BLOCK_START!r}"
    )
    assert CONTENT_BLOCK_END == "content_block:end", (
        f"Expected CONTENT_BLOCK_END='content_block:end', got {CONTENT_BLOCK_END!r}"
    )


# ---------------------------------------------------------------------------
# Test 15: content_block:start/end hook events emitted around each content block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_content_block_start_end() -> None:
    """content_block:start and content_block:end hook events emitted around each content block."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    response_with_blocks = {
        "content": "Here is my answer.",
        "text": "Here is my answer.",
        "tool_calls": None,
        "usage": None,
        "finish_reason": None,
        "content_blocks": [
            {"type": "thinking", "thinking": "Let me reason..."},
            {"type": "text", "text": "Here is my answer."},
        ],
    }

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": response_with_blocks,
        }
    )

    result = await orch.execute("Think about X", {}, client)
    assert result == "Here is my answer."

    # Collect all content_block:start and content_block:end events from hook_emit calls
    hook_emit_params = [
        params
        for method, params in client.requests
        if method == "request.hook_emit" and isinstance(params, dict)
    ]

    start_events = [
        p for p in hook_emit_params if p.get("event") == "content_block:start"
    ]
    end_events = [p for p in hook_emit_params if p.get("event") == "content_block:end"]

    # Verify 2 start and 2 end events (one per content block)
    assert len(start_events) == 2, (
        f"Expected 2 content_block:start events, got {len(start_events)}"
    )
    assert len(end_events) == 2, (
        f"Expected 2 content_block:end events, got {len(end_events)}"
    )

    # Verify payload shape: must contain block_type (str) and index (int)
    for event in start_events + end_events:
        data = event.get("data", {})
        assert "block_type" in data, (
            f"Expected 'block_type' in payload, got keys: {list(data.keys())}"
        )
        assert "index" in data, (
            f"Expected 'index' in payload, got keys: {list(data.keys())}"
        )
        assert isinstance(data["block_type"], str), (
            f"Expected block_type to be str, got {type(data['block_type'])}"
        )
        assert isinstance(data["index"], int), (
            f"Expected index to be int, got {type(data['index'])}"
        )

    # Verify correct ordering: start(0), end(0), start(1), end(1)
    content_block_events_in_order = [
        (params["event"], params["data"]["index"])
        for kind, method, params in client.call_log
        if kind == "request"
        and method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") in ("content_block:start", "content_block:end")
    ]

    expected_ordering = [
        ("content_block:start", 0),
        ("content_block:end", 0),
        ("content_block:start", 1),
        ("content_block:end", 1),
    ]
    assert content_block_events_in_order == expected_ordering, (
        f"Expected ordering {expected_ordering}, got {content_block_events_in_order}"
    )

    # Verify block types match the content blocks
    assert start_events[0]["data"]["block_type"] == "thinking", (
        f"Expected block_type='thinking' for block 0, got {start_events[0]['data']['block_type']!r}"
    )
    assert start_events[1]["data"]["block_type"] == "text", (
        f"Expected block_type='text' for block 1, got {start_events[1]['data']['block_type']!r}"
    )


# ---------------------------------------------------------------------------
# Test 16: execution:start is the very first hook event emitted by execute()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_execution_start() -> None:
    """execution:start must be the first hook event fired with payload {\"prompt\": ...}."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": chat_response("Hello!"),
        }
    )

    result = await orch.execute("Hello", {}, client)
    assert result == "Hello!"

    # Find all hook_emit calls in order
    hook_emit_calls = [
        params
        for kind, method, params in client.call_log
        if kind == "request"
        and method == "request.hook_emit"
        and isinstance(params, dict)
    ]

    assert len(hook_emit_calls) >= 1, "Expected at least one hook_emit call"

    # execution:start must be the very first hook event
    first_hook = hook_emit_calls[0]
    assert first_hook.get("event") == "execution:start", (
        f"Expected first hook event to be 'execution:start', got {first_hook.get('event')!r}"
    )

    # Payload must contain prompt
    data = first_hook.get("data", {})
    assert data.get("prompt") == "Hello", (
        f"Expected prompt='Hello' in execution:start payload, got {data.get('prompt')!r}"
    )


# ---------------------------------------------------------------------------
# Test 17: execution:end has status='completed' and response text on normal exit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_execution_end_completed() -> None:
    """execution:end must fire with status='completed' and the final response text on normal exit."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": chat_response("Final answer."),
        }
    )

    result = await orch.execute("Hello", {}, client)
    assert result == "Final answer."

    # Find execution:end hook_emit call
    execution_end_calls = [
        params
        for kind, method, params in client.call_log
        if kind == "request"
        and method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "execution:end"
    ]

    assert len(execution_end_calls) == 1, (
        f"Expected exactly 1 execution:end hook_emit, got {len(execution_end_calls)}"
    )

    data = execution_end_calls[0].get("data", {})
    assert data.get("status") == "completed", (
        f"Expected status='completed' in execution:end payload, got {data.get('status')!r}"
    )
    assert data.get("response") == "Final answer.", (
        f"Expected response='Final answer.' in execution:end payload, got {data.get('response')!r}"
    )


# ---------------------------------------------------------------------------
# Test 18: execution:end has status='cancelled' on cancelled exit path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_execution_end_cancelled() -> None:
    """execution:end must fire with status='cancelled' when orch._cancelled is set True mid-loop."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    # Custom client that sets _cancelled=True after provider_complete is called
    # so the cancellation checkpoint after the call fires.
    class CancellingClient(MockClient):
        def __init__(self, target_orch: Any, responses: dict) -> None:
            super().__init__(responses)
            self._target_orch = target_orch

        async def request(self, method: str, params: Any = None) -> Any:
            result = await super().request(method, params)
            if method == "request.provider_complete":
                self._target_orch._cancelled = True
            return result

    client = CancellingClient(
        orch,
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            # Return a response with tool_calls so the second cancellation
            # checkpoint (before tool dispatch) is reached.
            "request.provider_complete": chat_response(
                "partial response",
                tool_calls=[{"id": "c1", "tool": "my_tool", "arguments": {}}],
            ),
        },
    )

    result = await orch.execute("Hello", {}, client)
    assert result == "partial response"

    # Find execution:end hook_emit call
    execution_end_calls = [
        params
        for kind, method, params in client.call_log
        if kind == "request"
        and method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "execution:end"
    ]

    assert len(execution_end_calls) == 1, (
        f"Expected exactly 1 execution:end hook_emit, got {len(execution_end_calls)}"
    )

    data = execution_end_calls[0].get("data", {})
    assert data.get("status") == "cancelled", (
        f"Expected status='cancelled' in execution:end payload, got {data.get('status')!r}"
    )
    assert data.get("response") == "partial response", (
        f"Expected response='partial response' in execution:end payload, got {data.get('response')!r}"
    )


# ---------------------------------------------------------------------------
# Test 19: execution:end fires with status='error' even when provider raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_execution_end_error() -> None:
    """execution:end must fire with status='error' and response='' even when provider raises."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    class ProviderError(Exception):
        retryable = False

    orch = StreamingOrchestrator()

    class RaisingClient(MockClient):
        async def request(self, method: str, params: Any = None) -> Any:
            if method == "request.provider_complete":
                raise ProviderError("provider exploded")
            return await super().request(method, params)

    client = RaisingClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
        }
    )

    # execute() must re-raise the ProviderError
    with pytest.raises(ProviderError):
        await orch.execute("Hello", {}, client)

    # Despite the exception, execution:end must still have fired (via finally)
    execution_end_calls = [
        params
        for kind, method, params in client.call_log
        if kind == "request"
        and method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "execution:end"
    ]

    assert len(execution_end_calls) == 1, (
        f"Expected exactly 1 execution:end hook_emit on error path, got {len(execution_end_calls)}"
    )

    data = execution_end_calls[0].get("data", {})
    assert data.get("status") == "error", (
        f"Expected status='error' in execution:end payload, got {data.get('status')!r}"
    )
    assert data.get("response") == "", (
        f"Expected response='' in execution:end payload on error path, got {data.get('response')!r}"
    )


# ---------------------------------------------------------------------------
# Test 20: provider:resolve emitted after execution:start, before prompt:submit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_provider_resolve() -> None:
    """provider:resolve must be emitted exactly once with payload {\"provider\": ...} between execution:start and prompt:submit."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": chat_response("Hello!"),
        }
    )

    result = await orch.execute("Hi", {"provider_name": "anthropic"}, client)
    assert result == "Hello!"

    # Collect all hook_emit calls in order
    hook_emit_events = [
        (i, params)
        for i, (kind, method, params) in enumerate(client.call_log)
        if kind == "request"
        and method == "request.hook_emit"
        and isinstance(params, dict)
    ]

    # Find provider:resolve events
    provider_resolve_events = [
        (i, params)
        for i, params in hook_emit_events
        if params.get("event") == "provider:resolve"
    ]

    # Verify exactly 1 provider:resolve event
    assert len(provider_resolve_events) == 1, (
        f"Expected exactly 1 provider:resolve hook_emit, got {len(provider_resolve_events)}"
    )

    # Verify payload contains the resolved provider name
    data = provider_resolve_events[0][1].get("data", {})
    assert data.get("provider") == "anthropic", (
        f"Expected provider='anthropic' in provider:resolve payload, got {data.get('provider')!r}"
    )

    # Verify ordering: execution:start < provider:resolve < prompt:submit
    execution_start_indices = [
        i for i, params in hook_emit_events if params.get("event") == "execution:start"
    ]
    prompt_submit_indices = [
        i for i, params in hook_emit_events if params.get("event") == "prompt:submit"
    ]

    assert len(execution_start_indices) >= 1, (
        "Expected at least one execution:start event"
    )
    assert len(prompt_submit_indices) >= 1, "Expected at least one prompt:submit event"

    exec_start_idx = execution_start_indices[0]
    provider_resolve_idx = provider_resolve_events[0][0]
    prompt_submit_idx = prompt_submit_indices[0]

    assert exec_start_idx < provider_resolve_idx, (
        f"execution:start (call_log idx {exec_start_idx}) must come before "
        f"provider:resolve (call_log idx {provider_resolve_idx})"
    )
    assert provider_resolve_idx < prompt_submit_idx, (
        f"provider:resolve (call_log idx {provider_resolve_idx}) must come before "
        f"prompt:submit (call_log idx {prompt_submit_idx})"
    )


# ---------------------------------------------------------------------------
# Test 21: llm:request emitted before provider_complete call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_llm_request() -> None:
    """llm:request hook event emitted before provider_complete with correct payload."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": chat_response("Hello!"),
        }
    )

    result = await orch.execute("Hi", {"provider_name": "claude"}, client)
    assert result == "Hello!"

    # Find all llm:request hook_emit calls
    llm_request_calls = [
        params
        for kind, method, params in client.call_log
        if kind == "request"
        and method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "llm:request"
    ]

    # Verify exactly 1 llm:request event
    assert len(llm_request_calls) == 1, (
        f"Expected exactly 1 llm:request hook_emit, got {len(llm_request_calls)}"
    )

    # Verify payload
    data = llm_request_calls[0].get("data", {})
    assert data.get("provider") == "claude", (
        f"Expected provider='claude' in llm:request payload, got {data.get('provider')!r}"
    )
    assert data.get("message_count") == 0, (
        f"Expected message_count=0 in llm:request payload, got {data.get('message_count')!r}"
    )
    assert data.get("iteration") == 1, (
        f"Expected iteration=1 in llm:request payload, got {data.get('iteration')!r}"
    )

    # Verify ordering: llm:request comes before provider_complete in call_log
    llm_request_idx = next(
        i
        for i, (kind, method, params) in enumerate(client.call_log)
        if kind == "request"
        and method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "llm:request"
    )
    provider_complete_idx = next(
        i
        for i, (kind, method, _) in enumerate(client.call_log)
        if kind == "request" and method == "request.provider_complete"
    )
    assert llm_request_idx < provider_complete_idx, (
        f"llm:request (call_log idx {llm_request_idx}) must come before "
        f"provider_complete (call_log idx {provider_complete_idx})"
    )


# ---------------------------------------------------------------------------
# Test 22: llm:response emitted after provider_complete, before provider:response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_llm_response() -> None:
    """llm:response hook event emitted after provider_complete with correct payload."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    provider_result = {
        "content": "Response text.",
        "text": "Response text.",
        "tool_calls": None,
        "usage": {"input_tokens": 50, "output_tokens": 20},
        "finish_reason": None,
    }

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": provider_result,
        }
    )

    result = await orch.execute("Hello", {"provider_name": "anthropic"}, client)
    assert result == "Response text."

    # Find all llm:response hook_emit calls
    llm_response_calls = [
        params
        for kind, method, params in client.call_log
        if kind == "request"
        and method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "llm:response"
    ]

    # Verify exactly 1 llm:response event
    assert len(llm_response_calls) == 1, (
        f"Expected exactly 1 llm:response hook_emit, got {len(llm_response_calls)}"
    )

    # Verify payload
    data = llm_response_calls[0].get("data", {})
    assert data.get("provider") == "anthropic", (
        f"Expected provider='anthropic' in llm:response payload, got {data.get('provider')!r}"
    )
    assert data.get("status") == "ok", (
        f"Expected status='ok' in llm:response payload, got {data.get('status')!r}"
    )

    # Verify usage contains input_tokens=50, output_tokens=20 (dict or Pydantic model)
    usage = data.get("usage")
    assert usage is not None, "Expected usage to be present in llm:response payload"
    if isinstance(usage, dict):
        assert usage.get("input_tokens") == 50, (
            f"Expected input_tokens=50, got {usage.get('input_tokens')!r}"
        )
        assert usage.get("output_tokens") == 20, (
            f"Expected output_tokens=20, got {usage.get('output_tokens')!r}"
        )
    else:
        assert getattr(usage, "input_tokens", None) == 50, (
            f"Expected input_tokens=50, got {getattr(usage, 'input_tokens', None)!r}"
        )
        assert getattr(usage, "output_tokens", None) == 20, (
            f"Expected output_tokens=20, got {getattr(usage, 'output_tokens', None)!r}"
        )

    # Verify ordering: llm:response comes before provider:response in hook events
    hook_event_order = [
        (i, params.get("event"))
        for i, (kind, method, params) in enumerate(client.call_log)
        if kind == "request"
        and method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") in ("llm:response", "provider:response")
    ]

    assert len(hook_event_order) >= 2, (
        f"Expected both llm:response and provider:response events, got: {hook_event_order}"
    )

    llm_response_log_idx = next(
        i for i, event in hook_event_order if event == "llm:response"
    )
    provider_response_log_idx = next(
        i for i, event in hook_event_order if event == "provider:response"
    )
    assert llm_response_log_idx < provider_response_log_idx, (
        f"llm:response (call_log idx {llm_response_log_idx}) must come before "
        f"provider:response (call_log idx {provider_response_log_idx})"
    )
