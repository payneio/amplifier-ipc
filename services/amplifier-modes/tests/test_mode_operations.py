"""Tests for ModeHooks accessor methods: set_active_mode, clear_active_mode, get_active_mode."""

from __future__ import annotations

import asyncio
import json

import pytest

from amplifier_modes.__main__ import ModeServer
from amplifier_modes.hooks.mode import ModeDefinition, ModeHooks
from amplifier_modes.tools.mode import ModeTool


def make_mode(name: str = "test-mode") -> ModeDefinition:
    """Create a minimal ModeDefinition for testing."""
    return ModeDefinition(name=name, description="Test mode")


def test_get_active_mode_returns_none_by_default() -> None:
    """Fresh ModeHooks has no active mode."""
    hooks = ModeHooks()
    assert hooks.get_active_mode() is None


def test_set_active_mode_stores_mode() -> None:
    """set_active_mode stores mode retrievable via get_active_mode."""
    hooks = ModeHooks()
    mode = make_mode("plan")
    hooks.set_active_mode(mode)
    assert hooks.get_active_mode() is mode


def test_set_active_mode_clears_warned_tools() -> None:
    """set_active_mode resets _warned_tools set."""
    hooks = ModeHooks()
    # Populate _warned_tools directly to simulate prior state
    hooks._warned_tools.add("plan:bash")
    hooks._warned_tools.add("plan:write_file")
    mode = make_mode("plan")
    hooks.set_active_mode(mode)
    assert hooks._warned_tools == set()


def test_clear_active_mode_removes_mode() -> None:
    """clear_active_mode sets active mode back to None."""
    hooks = ModeHooks()
    mode = make_mode("debug")
    hooks.set_active_mode(mode)
    hooks.clear_active_mode()
    assert hooks.get_active_mode() is None


def test_clear_active_mode_clears_warned_tools() -> None:
    """clear_active_mode resets _warned_tools set."""
    hooks = ModeHooks()
    hooks._warned_tools.add("debug:bash")
    hooks.clear_active_mode()
    assert hooks._warned_tools == set()


def test_clear_active_mode_is_idempotent() -> None:
    """Clearing when nothing active does not raise."""
    hooks = ModeHooks()
    # Should not raise even with no active mode
    hooks.clear_active_mode()
    hooks.clear_active_mode()
    assert hooks.get_active_mode() is None


# ---------------------------------------------------------------------------
# ModeServer wiring tests
# ---------------------------------------------------------------------------


class _MockWriter:
    """Collects bytes written via write()/drain() for later assertion."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass  # no-op for testing

    @property
    def messages(self) -> list[dict]:
        """Parse all written newline-delimited JSON messages."""
        result = []
        for line in self._buf.split(b"\n"):
            stripped = line.strip()
            if stripped:
                result.append(json.loads(stripped))
        return result


@pytest.mark.asyncio
async def test_mode_server_wires_tool_to_hook() -> None:
    """ModeServer wires ModeTool._mode_hooks to the ModeHooks instance after configure."""
    server = ModeServer("amplifier_modes")
    reader = asyncio.StreamReader()
    writer = _MockWriter()

    request = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "configure", "params": {}})
        + "\n"
    )
    reader.feed_data(request.encode())
    reader.feed_eof()

    await server.handle_stream(reader, writer)

    mode_tool = server._tools.get("mode")
    assert mode_tool is not None, "ModeTool 'mode' must be registered"
    assert hasattr(mode_tool, "_mode_hooks"), (
        "ModeTool must have _mode_hooks attribute after wiring"
    )
    assert isinstance(mode_tool._mode_hooks, ModeHooks), (
        f"Expected _mode_hooks to be ModeHooks instance, got: {type(mode_tool._mode_hooks)}"
    )


@pytest.mark.asyncio
async def test_mode_server_describe_still_works() -> None:
    """ModeServer describe response includes 'mode' in tool names (no regression)."""
    server = ModeServer("amplifier_modes")
    reader = asyncio.StreamReader()
    writer = _MockWriter()

    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "describe"}) + "\n"
    reader.feed_data(request.encode())
    reader.feed_eof()

    await server.handle_stream(reader, writer)

    messages = writer.messages
    assert len(messages) == 1, f"Expected 1 response, got {len(messages)}"
    assert "result" in messages[0], f"Expected 'result' in response, got: {messages[0]}"

    result = messages[0]["result"]
    tools = result["capabilities"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "mode" in tool_names, f"Expected 'mode' in tool names; found: {tool_names}"


# ---------------------------------------------------------------------------
# _handle_current operation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_current_returns_none_when_no_mode_active() -> None:
    """_handle_current returns active_mode=None when ModeHooks has no active mode."""
    tool = ModeTool()
    hooks = ModeHooks()
    tool._mode_hooks = hooks  # wire hooks with no active mode

    result = await tool.execute({"operation": "current"})

    assert result.success is True
    assert result.output is not None
    assert result.output["active_mode"] is None


@pytest.mark.asyncio
async def test_current_returns_mode_info_when_active() -> None:
    """_handle_current returns name and description when a mode is active."""
    tool = ModeTool()
    hooks = ModeHooks()
    focus_mode = ModeDefinition(name="focus", description="Deep work mode")
    hooks.set_active_mode(focus_mode)
    tool._mode_hooks = hooks

    result = await tool.execute({"operation": "current"})

    assert result.success is True
    assert result.output is not None
    assert result.output["active_mode"] == "focus"
    assert result.output["description"] == "Deep work mode"


@pytest.mark.asyncio
async def test_current_returns_error_when_hooks_not_wired() -> None:
    """_handle_current returns not_ready error when _mode_hooks is None."""
    tool = ModeTool()
    # Do NOT set _mode_hooks — leave it as the class default (None)

    result = await tool.execute({"operation": "current"})

    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == "not_ready"
