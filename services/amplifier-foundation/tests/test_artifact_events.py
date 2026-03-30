"""Tests for artifact:write event emission from WriteTool."""

from __future__ import annotations

from typing import Any

import pytest

from amplifier_foundation.tools.filesystem.edit import EditTool
from amplifier_foundation.tools.filesystem.read import ReadTool
from amplifier_foundation.tools.filesystem.write import WriteTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockClient:
    """Records IPC request calls made by the tool."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def request(self, method: str, params: Any = None) -> Any:
        self.calls.append((method, params))
        return {}


def _hook_emits(client: MockClient) -> list[dict[str, Any]]:
    """Extract hook_emit payloads from a MockClient's recorded calls.

    Returns a list of ``data`` dicts from each ``request.hook_emit`` call.
    """
    return [
        params["data"]
        for method, params in client.calls
        if method == "request.hook_emit"
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_tool_emits_artifact_write(tmp_path: Any) -> None:
    """WriteTool emits artifact:write event with path and bytes on success."""
    from amplifier_ipc_protocol.events import ARTIFACT_WRITE

    target = tmp_path / "output.txt"
    content = "hello world"
    client = MockClient()

    tool = WriteTool(config={"allowed_write_paths": [str(tmp_path)]})
    tool.client = client

    result = await tool.execute({"file_path": str(target), "content": content})

    assert result.success is True

    emits = _hook_emits(client)
    assert len(emits) == 1

    # Verify event name
    method_calls = [(m, p) for m, p in client.calls if m == "request.hook_emit"]
    assert len(method_calls) == 1
    _, params = method_calls[0]
    assert params["event"] == ARTIFACT_WRITE

    # Verify payload
    assert emits[0]["path"] == str(target)
    assert emits[0]["bytes"] == len(content.encode("utf-8"))


@pytest.mark.asyncio
async def test_write_tool_no_event_on_failure(tmp_path: Any) -> None:
    """WriteTool does NOT emit any event when the write fails (path denied)."""
    client = MockClient()

    # Use a restrictive allowed_write_paths so the write will be denied
    tool = WriteTool(config={"allowed_write_paths": [str(tmp_path / "allowed")]})
    tool.client = client

    target = tmp_path / "denied" / "file.txt"
    result = await tool.execute({"file_path": str(target), "content": "data"})

    assert result.success is False
    assert _hook_emits(client) == []


@pytest.mark.asyncio
async def test_write_tool_works_without_client(tmp_path: Any) -> None:
    """WriteTool works correctly when client is None (no server injection)."""
    target = tmp_path / "file.txt"
    content = "no client needed"

    tool = WriteTool(config={"allowed_write_paths": [str(tmp_path)]})
    # client is None by default — no injection

    result = await tool.execute({"file_path": str(target), "content": content})

    assert result.success is True
    assert target.read_text(encoding="utf-8") == content


# ---------------------------------------------------------------------------
# EditTool artifact:write tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_tool_emits_artifact_write(tmp_path: Any) -> None:
    """EditTool emits artifact:write event with path and bytes on successful edit."""
    from amplifier_ipc_protocol.events import ARTIFACT_WRITE

    target = tmp_path / "file.txt"
    target.write_text("hello world", encoding="utf-8")
    client = MockClient()

    tool = EditTool(config={"allowed_write_paths": [str(tmp_path)]})
    tool.client = client

    result = await tool.execute(
        {
            "file_path": str(target),
            "old_string": "hello",
            "new_string": "goodbye",
        }
    )

    assert result.success is True

    emits = _hook_emits(client)
    assert len(emits) == 1

    # Verify event name
    method_calls = [(m, p) for m, p in client.calls if m == "request.hook_emit"]
    assert len(method_calls) == 1
    _, params = method_calls[0]
    assert params["event"] == ARTIFACT_WRITE

    # Verify payload
    expected_bytes = len("goodbye world".encode("utf-8"))
    assert emits[0]["path"] == str(target)
    assert emits[0]["bytes"] == expected_bytes


@pytest.mark.asyncio
async def test_edit_tool_no_event_on_failure(tmp_path: Any) -> None:
    """EditTool does NOT emit any event when the edit fails (nonexistent file)."""
    client = MockClient()

    tool = EditTool(config={"allowed_write_paths": [str(tmp_path)]})
    tool.client = client

    # Target file does not exist — should fail
    target = tmp_path / "nonexistent.txt"
    result = await tool.execute(
        {
            "file_path": str(target),
            "old_string": "hello",
            "new_string": "goodbye",
        }
    )

    assert result.success is False
    assert _hook_emits(client) == []


# ---------------------------------------------------------------------------
# ReadTool artifact:read tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_tool_emits_artifact_read(tmp_path: Any) -> None:
    """ReadTool emits artifact:read event with path, is_directory=False, and lines_read on success."""
    from amplifier_ipc_protocol.events import ARTIFACT_READ

    target = tmp_path / "hello.txt"
    target.write_text("line one\nline two\nline three\n", encoding="utf-8")
    client = MockClient()

    tool = ReadTool()
    tool.client = client

    result = await tool.execute({"file_path": str(target)})

    assert result.success is True

    emits = _hook_emits(client)
    assert len(emits) == 1

    # Verify event name
    method_calls = [(m, p) for m, p in client.calls if m == "request.hook_emit"]
    assert len(method_calls) == 1
    _, params = method_calls[0]
    assert params["event"] == ARTIFACT_READ

    # Verify payload
    assert emits[0]["path"] == str(target)
    assert emits[0]["is_directory"] is False
    assert emits[0]["lines_read"] == 3


@pytest.mark.asyncio
async def test_read_tool_emits_artifact_read_for_directory(tmp_path: Any) -> None:
    """ReadTool emits artifact:read event with is_directory=True and entry_count for directories."""
    from amplifier_ipc_protocol.events import ARTIFACT_READ

    # Create some entries in the directory
    (tmp_path / "file1.txt").write_text("a", encoding="utf-8")
    (tmp_path / "file2.txt").write_text("b", encoding="utf-8")
    (tmp_path / "subdir").mkdir()
    client = MockClient()

    tool = ReadTool()
    tool.client = client

    result = await tool.execute({"file_path": str(tmp_path)})

    assert result.success is True

    emits = _hook_emits(client)
    assert len(emits) == 1

    # Verify event name
    method_calls = [(m, p) for m, p in client.calls if m == "request.hook_emit"]
    assert len(method_calls) == 1
    _, params = method_calls[0]
    assert params["event"] == ARTIFACT_READ

    # Verify payload
    assert emits[0]["path"] == str(tmp_path)
    assert emits[0]["is_directory"] is True
    assert emits[0]["entry_count"] == 3


@pytest.mark.asyncio
async def test_read_tool_no_event_on_failure(tmp_path: Any) -> None:
    """ReadTool does NOT emit any event when the read fails (nonexistent path)."""
    client = MockClient()

    tool = ReadTool()
    tool.client = client

    # Path does not exist — should fail
    target = tmp_path / "nonexistent.txt"
    result = await tool.execute({"file_path": str(target)})

    assert result.success is False
    assert _hook_emits(client) == []
