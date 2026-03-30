"""Tests for policy:violation event emission from ModeHooks."""

from __future__ import annotations

from typing import Any

import pytest

from amplifier_ipc_protocol.events import POLICY_VIOLATION
from amplifier_modes.hooks.mode import ModeDefinition, ModeHooks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockClient:
    """Records IPC request calls made by the hook."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def request(self, method: str, params: Any = None) -> Any:
        self.requests.append({"method": method, "params": params})
        return {}


def _make_mode_with_policy() -> ModeDefinition:
    """Return a ModeDefinition with explicit tool policies for testing."""
    return ModeDefinition(
        name="focus",
        description="Deep focus mode",
        safe_tools=["read_file", "grep"],
        warn_tools=["bash"],
        block_tools=["write_file"],
        default_action="block",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_violation_emitted_for_blocked_tool() -> None:
    """ModeHooks emits policy:violation when blocked tool 'write_file' is denied."""
    mock_client = MockClient()
    hooks = ModeHooks()
    hooks.client = mock_client
    hooks.set_active_mode(_make_mode_with_policy())

    result = await hooks.handle("tool:pre", {"tool_name": "write_file"})

    assert result.action.value == "DENY"
    assert len(mock_client.requests) == 1
    req = mock_client.requests[0]
    assert req["method"] == "request.hook_emit"
    assert req["params"]["event"] == POLICY_VIOLATION
    data = req["params"]["data"]
    assert data["tool_name"] == "write_file"
    assert data["mode"] == "focus"
    assert "reason" in data


@pytest.mark.asyncio
async def test_policy_violation_emitted_for_warn_first_tool() -> None:
    """ModeHooks emits policy:violation on first call to warn tool 'bash'."""
    mock_client = MockClient()
    hooks = ModeHooks()
    hooks.client = mock_client
    hooks.set_active_mode(_make_mode_with_policy())

    result = await hooks.handle("tool:pre", {"tool_name": "bash"})

    assert result.action.value == "DENY"
    assert len(mock_client.requests) == 1
    req = mock_client.requests[0]
    assert req["params"]["event"] == POLICY_VIOLATION
    data = req["params"]["data"]
    assert data["tool_name"] == "bash"
    assert data["mode"] == "focus"
    assert "reason" in data


@pytest.mark.asyncio
async def test_no_policy_violation_for_warn_first_tool_second_call() -> None:
    """No policy:violation on second call to 'bash' (already warned)."""
    mock_client = MockClient()
    hooks = ModeHooks()
    hooks.client = mock_client
    hooks.set_active_mode(_make_mode_with_policy())

    # First call — triggers warn and DENY
    await hooks.handle("tool:pre", {"tool_name": "bash"})

    # Clear requests between calls
    mock_client.requests.clear()

    # Second call — should be allowed without emitting event
    result = await hooks.handle("tool:pre", {"tool_name": "bash"})

    assert result.action.value == "CONTINUE"
    assert len(mock_client.requests) == 0


@pytest.mark.asyncio
async def test_policy_violation_emitted_for_unlisted_tool() -> None:
    """policy:violation emitted for 'some_unknown_tool' with default_action=block."""
    mock_client = MockClient()
    hooks = ModeHooks()
    hooks.client = mock_client
    hooks.set_active_mode(_make_mode_with_policy())

    result = await hooks.handle("tool:pre", {"tool_name": "some_unknown_tool"})

    assert result.action.value == "DENY"
    assert len(mock_client.requests) == 1
    req = mock_client.requests[0]
    assert req["params"]["event"] == POLICY_VIOLATION
    data = req["params"]["data"]
    assert data["tool_name"] == "some_unknown_tool"
    assert data["mode"] == "focus"
    assert "reason" in data


@pytest.mark.asyncio
async def test_no_policy_violation_for_safe_tool() -> None:
    """No events emitted for 'read_file' (safe tool)."""
    mock_client = MockClient()
    hooks = ModeHooks()
    hooks.client = mock_client
    hooks.set_active_mode(_make_mode_with_policy())

    result = await hooks.handle("tool:pre", {"tool_name": "read_file"})

    assert result.action.value == "CONTINUE"
    assert len(mock_client.requests) == 0


@pytest.mark.asyncio
async def test_no_policy_violation_when_no_mode_active() -> None:
    """No events emitted when no mode is set."""
    mock_client = MockClient()
    hooks = ModeHooks()
    hooks.client = mock_client
    # No mode set — hooks has no active mode

    result = await hooks.handle("tool:pre", {"tool_name": "write_file"})

    assert result.action.value == "CONTINUE"
    assert len(mock_client.requests) == 0


@pytest.mark.asyncio
async def test_policy_violation_works_without_client() -> None:
    """No crash when client is None. write_file still gets DENY."""
    hooks = ModeHooks()
    # client defaults to None — do not set
    hooks.set_active_mode(_make_mode_with_policy())

    # _emit_policy_violation should short-circuit silently when client is None
    result = await hooks.handle("tool:pre", {"tool_name": "write_file"})

    assert result.action.value == "DENY"
