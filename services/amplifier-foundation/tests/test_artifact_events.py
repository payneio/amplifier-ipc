"""Tests for artifact:write event emission from WriteTool."""

from __future__ import annotations

from typing import Any

import pytest

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
