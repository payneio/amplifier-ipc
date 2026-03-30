"""Tests for DelegateTool — session spawning and resuming via IPC client."""

from __future__ import annotations

from typing import Any

import pytest

from amplifier_foundation.tools.delegate import DelegateTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeClient:
    """Records calls and returns canned responses."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._responses: dict[str, Any] = responses or {}

    async def request(self, method: str, params: Any = None) -> Any:
        self.calls.append((method, params))
        return self._responses.get(method, {})


class FailingClient:
    """Always raises on request."""

    async def request(self, method: str, params: Any = None) -> Any:
        raise RuntimeError("Connection failed")


def make_spawn_response(
    session_id: str = "test-session-123",
    response: str = "Done.",
    turn_count: int = 3,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "response": response,
        "turn_count": turn_count,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delegate_tool_sends_session_spawn() -> None:
    """DelegateTool calls request.session_spawn with correct agent and instruction."""
    tool = DelegateTool()
    tool.client = FakeClient(
        responses={
            "request.session_spawn": make_spawn_response(
                session_id="sess-abc", response="Task completed."
            )
        }
    )

    result = await tool.execute(
        {
            "agent": "foundation:explorer",
            "instruction": "Explore the codebase",
        }
    )

    assert result.success is True
    session_calls = [(m, p) for m, p in tool.client.calls if m != "request.hook_emit"]
    assert len(session_calls) == 1
    method, params = session_calls[0]
    assert method == "request.session_spawn"
    assert params["agent"] == "foundation:explorer"
    assert params["instruction"] == "Explore the codebase"
    assert "[Delegate session: sess-abc]" in result.output
    assert "Task completed." in result.output


@pytest.mark.asyncio
async def test_delegate_tool_defaults_agent_to_self() -> None:
    """DelegateTool defaults agent to 'self' when not specified."""
    tool = DelegateTool()
    tool.client = FakeClient(
        responses={
            "request.session_spawn": make_spawn_response(),
        }
    )

    result = await tool.execute({"instruction": "Do something"})

    assert result.success is True
    session_calls = [(m, p) for m, p in tool.client.calls if m != "request.hook_emit"]
    assert len(session_calls) == 1
    method, params = session_calls[0]
    assert method == "request.session_spawn"
    assert params["agent"] == "self"


@pytest.mark.asyncio
async def test_delegate_tool_resumes_session() -> None:
    """DelegateTool calls request.session_resume when session_id is provided."""
    tool = DelegateTool()
    tool.client = FakeClient(
        responses={
            "request.session_resume": make_spawn_response(
                session_id="existing-session", response="Resumed successfully."
            ),
        }
    )

    result = await tool.execute(
        {
            "session_id": "existing-session",
            "instruction": "Continue the task",
        }
    )

    assert result.success is True
    session_calls = [(m, p) for m, p in tool.client.calls if m != "request.hook_emit"]
    assert len(session_calls) == 1
    method, params = session_calls[0]
    assert method == "request.session_resume"
    assert params["session_id"] == "existing-session"
    assert params["instruction"] == "Continue the task"
    assert "[Delegate session: existing-session]" in result.output
    assert "Resumed successfully." in result.output


@pytest.mark.asyncio
async def test_delegate_tool_handles_error_response() -> None:
    """DelegateTool catches exceptions and returns ToolResult(success=False)."""
    tool = DelegateTool()
    tool.client = FailingClient()

    result = await tool.execute(
        {
            "agent": "foundation:explorer",
            "instruction": "Explore the codebase",
        }
    )

    assert result.success is False
    assert result.error is not None
    error_msg = (
        result.error.get("message", "")
        if isinstance(result.error, dict)
        else str(result.error)
    )
    assert "Connection failed" in error_msg


# ---------------------------------------------------------------------------
# Lifecycle event helpers and tests
# ---------------------------------------------------------------------------


def _hook_emits(client: Any, event: str) -> list[dict[str, Any]]:
    """Extract data payloads for all hook_emit calls matching the given event."""
    results = []
    for method, params in client.calls:
        if method == "request.hook_emit" and params and params.get("event") == event:
            results.append(params.get("data", {}))
    return results


@pytest.mark.asyncio
async def test_delegate_emits_agent_spawned_and_completed() -> None:
    """DelegateTool emits delegate:agent_spawned before and delegate:agent_completed after spawn."""
    tool = DelegateTool()
    tool.client = FakeClient(
        responses={
            "request.session_spawn": make_spawn_response(
                session_id="sess-new", response="Done.", turn_count=2
            )
        }
    )

    await tool.execute(
        {
            "agent": "foundation:explorer",
            "instruction": "Explore the codebase",
        }
    )

    spawned = _hook_emits(tool.client, "delegate:agent_spawned")
    completed = _hook_emits(tool.client, "delegate:agent_completed")

    assert spawned[0]["agent"] == "foundation:explorer"
    assert completed[0]["agent"] == "foundation:explorer"
    assert completed[0]["sub_session_id"] == "sess-new"
    assert completed[0]["success"] is True


@pytest.mark.asyncio
async def test_delegate_emits_agent_resumed_and_completed() -> None:
    """DelegateTool emits delegate:agent_resumed (NOT agent_spawned) for resume."""
    tool = DelegateTool()
    tool.client = FakeClient(
        responses={
            "request.session_resume": make_spawn_response(
                session_id="existing-sess", response="Continued.", turn_count=5
            )
        }
    )

    await tool.execute(
        {
            "session_id": "existing-sess",
            "instruction": "Continue the task",
        }
    )

    resumed = _hook_emits(tool.client, "delegate:agent_resumed")
    spawned = _hook_emits(tool.client, "delegate:agent_spawned")
    completed = _hook_emits(tool.client, "delegate:agent_completed")

    assert resumed[0]["session_id"] == "existing-sess"
    assert len(spawned) == 0
    assert completed[0]["sub_session_id"] == "existing-sess"


@pytest.mark.asyncio
async def test_delegate_emits_error_on_failure() -> None:
    """Basic test with FailingClient — verify result.success is False."""
    tool = DelegateTool()
    tool.client = FailingClient()

    result = await tool.execute(
        {
            "agent": "foundation:explorer",
            "instruction": "Explore the codebase",
        }
    )

    assert result.success is False


class SpawnFailingClient:
    """Records hook_emit calls but raises RuntimeError on session_spawn."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def request(self, method: str, params: Any = None) -> Any:
        self.calls.append((method, params))
        if method == "request.session_spawn":
            raise RuntimeError("Spawn failed")
        return {}


@pytest.mark.asyncio
async def test_delegate_emits_error_with_recording_client() -> None:
    """SpawnFailingClient: delegate:agent_spawned before failure, delegate:error after."""
    tool = DelegateTool()
    client = SpawnFailingClient()
    tool.client = client

    await tool.execute(
        {
            "agent": "foundation:explorer",
            "instruction": "Explore the codebase",
        }
    )

    spawned = _hook_emits(client, "delegate:agent_spawned")
    errors = _hook_emits(client, "delegate:error")

    assert spawned[0]["agent"] == "foundation:explorer"
    assert errors[0]["agent"] == "foundation:explorer"
    assert "Spawn failed" in errors[0]["error"]


@pytest.mark.asyncio
async def test_delegate_no_completed_on_failure() -> None:
    """SpawnFailingClient: delegate:agent_completed is NOT emitted on failure."""
    tool = DelegateTool()
    client = SpawnFailingClient()
    tool.client = client

    await tool.execute(
        {
            "agent": "foundation:explorer",
            "instruction": "Explore the codebase",
        }
    )

    completed = _hook_emits(client, "delegate:agent_completed")
    assert len(completed) == 0
