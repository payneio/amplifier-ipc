"""Integration tests for the amplifier_foundation service.

Tests the full service handling actual JSON-RPC requests for tool execution,
content reading, hook emit, and sequential requests.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from amplifier_ipc_protocol.server import Server


# ---------------------------------------------------------------------------
# Infrastructure
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


async def _send_messages(messages: list[dict]) -> list[dict]:
    """Send a list of JSON-RPC messages to Server('amplifier_foundation') and collect responses.

    Creates a real Server instance for 'amplifier_foundation', feeds the
    messages through handle_stream, and returns all response dicts.
    """
    server = Server("amplifier_foundation")
    reader = asyncio.StreamReader()
    writer = _MockWriter()

    for msg in messages:
        data = (json.dumps(msg) + "\n").encode()
        reader.feed_data(data)

    reader.feed_eof()
    await server.handle_stream(reader, writer)
    return writer.messages


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_execute_todo_create() -> None:
    """tool.execute for todo create returns success=True and count=1."""
    responses = await _send_messages(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tool.execute",
                "params": {
                    "name": "todo",
                    "input": {
                        "action": "create",
                        "todos": [
                            {
                                "content": "Write integration tests",
                                "status": "in_progress",
                                "activeForm": "Writing integration tests",
                            }
                        ],
                    },
                },
            }
        ]
    )

    assert len(responses) == 1
    assert "result" in responses[0], f"Expected 'result', got: {responses[0]}"
    result = responses[0]["result"]
    assert result["success"] is True
    assert result["output"]["count"] == 1


@pytest.mark.asyncio
async def test_tool_execute_unknown_tool() -> None:
    """tool.execute for a nonexistent tool returns a JSON-RPC error response."""
    responses = await _send_messages(
        [
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tool.execute",
                "params": {
                    "name": "nonexistent_tool",
                    "input": {},
                },
            }
        ]
    )

    assert len(responses) == 1
    assert "error" in responses[0], f"Expected 'error', got: {responses[0]}"
    assert responses[0]["error"]["code"] == -32602  # INVALID_PARAMS


@pytest.mark.asyncio
async def test_content_read_agent_file() -> None:
    """content.read for agents/explorer.md returns non-empty content."""
    responses = await _send_messages(
        [
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "content.read",
                "params": {"path": "agents/explorer.md"},
            }
        ]
    )

    assert len(responses) == 1
    assert "result" in responses[0], f"Expected 'result', got: {responses[0]}"
    content = responses[0]["result"]["content"]
    assert isinstance(content, str)
    assert len(content.strip()) > 0, "Content of agents/explorer.md should not be empty"


@pytest.mark.asyncio
async def test_content_list_agents() -> None:
    """content.list with prefix='agents/' returns >=5 paths."""
    responses = await _send_messages(
        [
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "content.list",
                "params": {"prefix": "agents/"},
            }
        ]
    )

    assert len(responses) == 1
    assert "result" in responses[0], f"Expected 'result', got: {responses[0]}"
    paths = responses[0]["result"]["paths"]
    agent_paths = [p for p in paths if p.startswith("agents/")]
    assert len(agent_paths) >= 5, (
        f"Expected >= 5 agent paths, got {len(agent_paths)}: {agent_paths}"
    )


@pytest.mark.asyncio
async def test_hook_emit_returns_hook_result() -> None:
    """hook.emit for provider:request returns a result with an action field."""
    responses = await _send_messages(
        [
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "hook.emit",
                "params": {
                    "event": "provider:request",
                    "data": {"session_id": "test-session-123"},
                },
            }
        ]
    )

    assert len(responses) == 1
    assert "result" in responses[0], f"Expected 'result', got: {responses[0]}"
    result = responses[0]["result"]
    assert "action" in result, f"Expected 'action' in hook result, got: {result}"


@pytest.mark.asyncio
async def test_multiple_requests_in_sequence() -> None:
    """Sends describe + tool.execute + content.list in sequence; all 3 responses correct."""
    responses = await _send_messages(
        [
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "describe",
            },
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tool.execute",
                "params": {
                    "name": "todo",
                    "input": {
                        "action": "create",
                        "todos": [
                            {
                                "content": "Sequential test task",
                                "status": "pending",
                                "activeForm": "Doing sequential test",
                            }
                        ],
                    },
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "content.list",
            },
        ]
    )

    assert len(responses) == 3, f"Expected 3 responses, got {len(responses)}"

    # Response 1: describe
    describe_resp = next(r for r in responses if r.get("id") == 10)
    assert "result" in describe_resp, (
        f"describe: expected 'result', got: {describe_resp}"
    )
    assert describe_resp["result"]["name"] == "amplifier_foundation"
    caps = describe_resp["result"]["capabilities"]
    tool_names = {t["name"] for t in caps.get("tools", [])}
    assert "todo" in tool_names, f"Expected 'todo' in tools, found: {tool_names}"

    # Response 2: tool.execute
    execute_resp = next(r for r in responses if r.get("id") == 11)
    assert "result" in execute_resp, (
        f"tool.execute: expected 'result', got: {execute_resp}"
    )
    assert execute_resp["result"]["success"] is True
    assert execute_resp["result"]["output"]["count"] == 1

    # Response 3: content.list
    list_resp = next(r for r in responses if r.get("id") == 12)
    assert "result" in list_resp, f"content.list: expected 'result', got: {list_resp}"
    assert len(list_resp["result"]["paths"]) > 0, (
        "content.list should return some paths"
    )
