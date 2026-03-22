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
    assert len(tool.client.calls) == 1
    method, params = tool.client.calls[0]
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
    assert len(tool.client.calls) == 1
    method, params = tool.client.calls[0]
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
    assert len(tool.client.calls) == 1
    method, params = tool.client.calls[0]
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
