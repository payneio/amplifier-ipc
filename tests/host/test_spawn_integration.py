"""Integration tests for spawn_child_session — only Host.run() is patched.

All three tests call the real spawn_child_session function; the only thing
mocked is Host.run() so that we never touch a real subprocess.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from amplifier_ipc.host.events import CompleteEvent, StreamTokenEvent
from amplifier_ipc.host.spawner import SpawnRequest, spawn_child_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_PARENT_CONFIG: dict = {
    "services": [],
    "orchestrator": "",
    "context_manager": "",
    "provider": "",
    "tools": [],
    "hooks": [],
}


# ---------------------------------------------------------------------------
# Test 1: end-to-end spawn
# ---------------------------------------------------------------------------


async def test_spawn_child_session_end_to_end() -> None:
    """Patches Host.run() to yield StreamTokenEvent then CompleteEvent.

    Verifies:
    - result has the correct response string
    - turn_count == 1
    - session_id starts with parent_session_id
    - session_id ends with '_self'
    - metadata has agent='self'
    """
    parent_session_id = "parent-abc123"
    transcript: list = []
    request = SpawnRequest(agent="self", instruction="Do something useful")

    async def mock_run(host_self: object, prompt: str):  # type: ignore[return]
        yield StreamTokenEvent(token="Hello ")
        yield CompleteEvent(result="Hello world")

    with patch("amplifier_ipc.host.host.Host.run", mock_run):
        result = await spawn_child_session(
            parent_session_id=parent_session_id,
            parent_config=_MINIMAL_PARENT_CONFIG,
            transcript=transcript,
            request=request,
            current_depth=0,
        )

    assert result["response"] == "Hello world"
    assert result["turn_count"] == 1
    assert result["session_id"].startswith(parent_session_id)
    assert result["session_id"].endswith("_self")
    assert result["metadata"]["agent"] == "self"


# ---------------------------------------------------------------------------
# Test 2: context_depth='all' with conversation scope
# ---------------------------------------------------------------------------


async def test_spawn_child_session_with_context_depth_all() -> None:
    """context_depth='all' + scope='conversation' includes user/assistant but excludes tool_result.

    Verifies that the instruction passed to the child Host contains user and
    assistant messages from the parent transcript but does NOT contain any
    tool_result role entries.
    """
    parent_session_id = "parent-xyz"
    transcript = [
        {"role": "user", "content": "Initial question"},
        {"role": "assistant", "content": "Initial answer"},
        {"role": "tool_result", "content": "Some tool output"},
        {"role": "user", "content": "Follow up question"},
    ]
    request = SpawnRequest(
        agent="self",
        instruction="Now do this task",
        context_depth="all",
        context_scope="conversation",
    )

    captured_instruction: list[str] = []

    async def mock_run(host_self: object, prompt: str):  # type: ignore[return]
        captured_instruction.append(prompt)
        yield CompleteEvent(result="done")

    with patch("amplifier_ipc.host.host.Host.run", mock_run):
        await spawn_child_session(
            parent_session_id=parent_session_id,
            parent_config=_MINIMAL_PARENT_CONFIG,
            transcript=transcript,
            request=request,
            current_depth=0,
        )

    assert captured_instruction, "mock_run was never called"
    instruction = captured_instruction[0]

    # User and assistant messages should appear in the instruction
    assert "Initial question" in instruction
    assert "Initial answer" in instruction
    assert "Follow up question" in instruction

    # tool_result messages must NOT appear
    assert "tool_result" not in instruction
    assert "Some tool output" not in instruction


# ---------------------------------------------------------------------------
# Test 3: self-delegation depth limit
# ---------------------------------------------------------------------------


async def test_spawn_self_delegation_depth_limit() -> None:
    """current_depth=3 raises ValueError matching 'Self-delegation depth limit'."""
    request = SpawnRequest(agent="self", instruction="Do something")

    with pytest.raises(ValueError, match="Self-delegation depth limit"):
        await spawn_child_session(
            parent_session_id="parent-123",
            parent_config={"tools": []},
            transcript=[],
            request=request,
            current_depth=3,
        )
