"""Tests for StreamingOrchestrator — discovery, IPC call routing, DENY handling."""

from __future__ import annotations

from typing import Any

import pytest
from amplifier_ipc_protocol.discovery import scan_package


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
    """

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.requests: list[tuple[str, Any]] = []
        self.notifications: list[tuple[str, Any]] = []
        self._responses: dict[str, Any] = responses or {}
        self._indices: dict[str, int] = {}

    async def request(self, method: str, params: Any = None) -> Any:
        self.requests.append((method, params))
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
