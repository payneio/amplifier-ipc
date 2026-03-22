"""Tests for TaskTool — always delegates to self via IPC client."""

from __future__ import annotations

from typing import Any

import pytest

from amplifier_foundation.tools.task import TaskTool


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
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_tool_sends_session_spawn() -> None:
    """TaskTool calls request.session_spawn with agent='self' and task as instruction."""
    tool = TaskTool()
    tool.client = FakeClient(
        responses={
            "request.session_spawn": make_spawn_response(
                session_id="task-sess-abc", response="Task completed."
            )
        }
    )

    result = await tool.execute({"task": "Do something important"})

    assert result.success is True
    assert len(tool.client.calls) == 1
    method, params = tool.client.calls[0]
    assert method == "request.session_spawn"
    assert params["agent"] == "self"
    assert params["instruction"] == "Do something important"
    assert "[Task session: task-sess-abc]" in result.output
    assert "Task completed." in result.output


@pytest.mark.asyncio
async def test_task_tool_uses_context_depth_none() -> None:
    """TaskTool always uses context_depth='none' and context_scope='conversation'."""
    tool = TaskTool()
    tool.client = FakeClient(
        responses={
            "request.session_spawn": make_spawn_response(),
        }
    )

    await tool.execute({"task": "Some task"})

    assert len(tool.client.calls) == 1
    _, params = tool.client.calls[0]
    assert params["context_depth"] == "none"
    assert params["context_scope"] == "conversation"


@pytest.mark.asyncio
async def test_task_tool_formats_output() -> None:
    """TaskTool formats output as '[Task session: {id}]\\n[Turns: {count}]\\n\\n{response}'."""
    tool = TaskTool()
    tool.client = FakeClient(
        responses={
            "request.session_spawn": make_spawn_response(
                session_id="sess-xyz",
                response="Work done.",
                turn_count=5,
            )
        }
    )

    result = await tool.execute({"task": "Do work"})

    assert result.success is True
    assert result.output == "[Task session: sess-xyz]\n[Turns: 5]\n\nWork done."


@pytest.mark.asyncio
async def test_task_tool_handles_error() -> None:
    """TaskTool catches exceptions and returns ToolResult(success=False)."""
    tool = TaskTool()
    tool.client = FailingClient()

    result = await tool.execute({"task": "Do something"})

    assert result.success is False
    assert result.error is not None
    error_msg = (
        result.error.get("message", "")
        if isinstance(result.error, dict)
        else str(result.error)
    )
    assert "Connection failed" in error_msg
