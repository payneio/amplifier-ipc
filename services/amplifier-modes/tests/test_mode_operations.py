"""Tests for ModeHooks accessor methods: set_active_mode, clear_active_mode, get_active_mode."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

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


# ---------------------------------------------------------------------------
# _handle_clear operation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_deactivates_active_mode() -> None:
    """_handle_clear calls clear_active_mode() so hook state becomes None."""
    tool = ModeTool()
    hooks = ModeHooks()
    focus_mode = ModeDefinition(name="focus", description="Deep work mode")
    hooks.set_active_mode(focus_mode)
    tool._mode_hooks = hooks

    result = await tool.execute({"operation": "clear"})

    assert result.success is True
    assert result.output is not None
    assert result.output["status"] == "cleared"
    # Verify the hook state was actually cleared
    assert hooks.get_active_mode() is None


@pytest.mark.asyncio
async def test_clear_is_idempotent() -> None:
    """_handle_clear with no active mode still returns success with status 'cleared'."""
    tool = ModeTool()
    hooks = ModeHooks()
    # No mode set — hooks has no active mode
    tool._mode_hooks = hooks

    result = await tool.execute({"operation": "clear"})

    assert result.success is True
    assert result.output is not None
    assert result.output["status"] == "cleared"
    assert hooks.get_active_mode() is None


@pytest.mark.asyncio
async def test_clear_returns_error_when_hooks_not_wired() -> None:
    """_handle_clear returns not_ready error when _mode_hooks is None."""
    tool = ModeTool()
    # Do NOT set _mode_hooks — leave it as the class default (None)

    result = await tool.execute({"operation": "clear"})

    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == "not_ready"


# ---------------------------------------------------------------------------
# _discover_modes tests
# ---------------------------------------------------------------------------


_SAMPLE_MODE_CONTENT = """\
---
mode:
  name: focus
  description: Deep focus mode
  shortcut: f
  tools:
    safe: [read_file, grep]
    warn: [bash]
  default_action: block
---
You are in focus mode. Only read and search.
"""

_SAMPLE_MODE_2_CONTENT = """\
---
mode:
  name: plan
  description: Planning mode
  shortcut: p
  tools:
    safe: [read_file, grep, write_file]
  default_action: allow
---
You are in planning mode. Think and discuss before acting.
"""


def _write_mode_file(base: Path, name: str, content: str) -> None:
    """Write a mode file to base/.amplifier/modes/name.md."""
    mode_dir = base / ".amplifier" / "modes"
    mode_dir.mkdir(parents=True, exist_ok=True)
    file_path = mode_dir / name
    file_path.write_text(content, encoding="utf-8")


def test_discover_modes_finds_project_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_discover_modes finds modes in the project-level .amplifier/modes/ directory."""
    _write_mode_file(tmp_path, "focus.md", _SAMPLE_MODE_CONTENT)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    # Patch home to somewhere that won't have modes
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "no-home"))

    tool = ModeTool()
    modes = tool._discover_modes()

    assert len(modes) == 1
    assert modes[0].name == "focus"
    assert modes[0].description == "Deep focus mode"
    assert modes[0].source is not None and modes[0].source.endswith("focus.md")


def test_discover_modes_finds_user_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_discover_modes finds modes in the user-level ~/.amplifier/modes/ directory."""
    home_dir = tmp_path / "home"
    _write_mode_file(home_dir, "focus.md", _SAMPLE_MODE_CONTENT)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home_dir))
    # Patch cwd to somewhere that won't have modes
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path / "no-project"))

    tool = ModeTool()
    modes = tool._discover_modes()

    assert len(modes) == 1
    assert modes[0].name == "focus"
    assert modes[0].description == "Deep focus mode"
    assert modes[0].source is not None and modes[0].source.endswith("focus.md")


def test_discover_modes_project_overrides_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project-level mode with same name overrides user-level mode."""
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"

    # User-level: focus mode with user description
    user_content = _SAMPLE_MODE_CONTENT.replace("Deep focus mode", "User focus mode")
    _write_mode_file(home_dir, "focus.md", user_content)

    # Project-level: focus mode with project description
    project_content = _SAMPLE_MODE_CONTENT.replace(
        "Deep focus mode", "Project focus mode"
    )
    _write_mode_file(project_dir, "focus.md", project_content)

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home_dir))
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: project_dir))

    tool = ModeTool()
    modes = tool._discover_modes()

    assert len(modes) == 1
    assert modes[0].description == "Project focus mode"


def test_discover_modes_missing_dirs_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_discover_modes returns empty list when neither directory exists."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "no-home"))
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path / "no-project"))

    tool = ModeTool()
    modes = tool._discover_modes()

    assert modes == []


def test_discover_modes_merges_both_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_discover_modes returns modes from both user and project directories when names differ."""
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"

    _write_mode_file(home_dir, "focus.md", _SAMPLE_MODE_CONTENT)
    _write_mode_file(project_dir, "plan.md", _SAMPLE_MODE_2_CONTENT)

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home_dir))
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: project_dir))

    tool = ModeTool()
    modes = tool._discover_modes()

    names = {m.name for m in modes}
    assert names == {"focus", "plan"}


# ---------------------------------------------------------------------------
# _handle_list operation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_discovered_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_handle_list returns modes discovered from filesystem with name/description/shortcut."""
    _write_mode_file(tmp_path, "focus.md", _SAMPLE_MODE_CONTENT)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "no-home"))

    tool = ModeTool()
    hooks = ModeHooks()
    tool._mode_hooks = hooks

    result = await tool.execute({"operation": "list"})

    assert result.success is True
    assert result.output is not None
    modes = result.output["modes"]
    assert len(modes) == 1
    assert modes[0]["name"] == "focus"
    assert modes[0]["description"] == "Deep focus mode"
    assert modes[0]["shortcut"] == "f"


@pytest.mark.asyncio
async def test_list_returns_empty_when_no_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_handle_list returns empty modes list when no mode files exist."""
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path / "no-project"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "no-home"))

    tool = ModeTool()
    hooks = ModeHooks()
    tool._mode_hooks = hooks

    result = await tool.execute({"operation": "list"})

    assert result.success is True
    assert result.output is not None
    assert result.output["modes"] == []


@pytest.mark.asyncio
async def test_list_returns_error_when_hooks_not_wired() -> None:
    """_handle_list returns not_ready error when _mode_hooks is None."""
    tool = ModeTool()
    # Do NOT set _mode_hooks — leave it as the class default (None)

    result = await tool.execute({"operation": "list"})

    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == "not_ready"


# ---------------------------------------------------------------------------
# _handle_set operation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_activates_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_handle_set activates the named mode and stores it in ModeHooks."""
    _write_mode_file(tmp_path, "focus.md", _SAMPLE_MODE_CONTENT)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "no-home"))

    tool = ModeTool()
    hooks = ModeHooks()
    tool._mode_hooks = hooks

    result = await tool.execute({"operation": "set", "name": "focus"})

    assert result.success is True
    assert result.output is not None
    assert result.output["name"] == "focus"
    assert "activated" in result.output["message"].lower()
    # Verify hook state was actually updated
    assert hooks.get_active_mode() is not None
    assert hooks.get_active_mode().name == "focus"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_set_unknown_mode_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_handle_set returns unknown_mode error when name not found, listing available modes."""
    _write_mode_file(tmp_path, "focus.md", _SAMPLE_MODE_CONTENT)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "no-home"))

    tool = ModeTool()
    hooks = ModeHooks()
    tool._mode_hooks = hooks

    result = await tool.execute({"operation": "set", "name": "nonexistent"})

    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == "unknown_mode"
    assert "nonexistent" in result.error["message"]
    assert "available" in result.error
    assert "focus" in result.error["available"]


@pytest.mark.asyncio
async def test_set_replaces_existing_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_handle_set replaces the existing active mode (set is not additive)."""
    _write_mode_file(tmp_path, "focus.md", _SAMPLE_MODE_CONTENT)
    _write_mode_file(tmp_path, "plan.md", _SAMPLE_MODE_2_CONTENT)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "no-home"))

    tool = ModeTool()
    hooks = ModeHooks()
    focus_mode = ModeDefinition(name="focus", description="Deep focus mode")
    hooks.set_active_mode(focus_mode)
    tool._mode_hooks = hooks

    result = await tool.execute({"operation": "set", "name": "plan"})

    assert result.success is True
    assert result.output is not None
    assert result.output["name"] == "plan"
    # Verify that plan is now active (not focus)
    active = hooks.get_active_mode()
    assert active is not None
    assert active.name == "plan"


@pytest.mark.asyncio
async def test_set_missing_name_returns_error() -> None:
    """_handle_set returns missing_name error when 'name' param is not provided."""
    tool = ModeTool()
    hooks = ModeHooks()
    tool._mode_hooks = hooks

    result = await tool.execute({"operation": "set"})

    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == "missing_name"


@pytest.mark.asyncio
async def test_set_returns_error_when_hooks_not_wired() -> None:
    """_handle_set returns not_ready error when _mode_hooks is None."""
    tool = ModeTool()
    # Do NOT set _mode_hooks — leave it as the class default (None)

    result = await tool.execute({"operation": "set", "name": "focus"})

    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == "not_ready"


@pytest.mark.asyncio
async def test_set_with_no_modes_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_handle_set returns unknown_mode error when no mode files exist on disk."""
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path / "no-project"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "no-home"))

    tool = ModeTool()
    hooks = ModeHooks()
    tool._mode_hooks = hooks

    result = await tool.execute({"operation": "set", "name": "focus"})

    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == "unknown_mode"
    assert result.error["available"] == []
