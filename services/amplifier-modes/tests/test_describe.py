"""Service describe verification — verifies the full service starts, responds to
describe, and reports all components correctly.

Uses a real Server('amplifier_modes') instance (no mock package) to exercise
the live discovery path end-to-end.
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


async def _send_describe() -> dict:
    """Create Server('amplifier_modes'), send a describe request, return result.

    Sends one JSON-RPC describe request over an asyncio.StreamReader, collects the
    response via _MockWriter, and returns the ``result`` dict from the response.
    """
    server = Server("amplifier_modes")
    reader = asyncio.StreamReader()
    writer = _MockWriter()

    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "describe"}) + "\n"
    reader.feed_data(request.encode())
    reader.feed_eof()

    await server.handle_stream(reader, writer)

    messages = writer.messages
    assert len(messages) == 1, f"Expected 1 response, got {len(messages)}"
    assert "result" in messages[0], f"Expected 'result' in response, got: {messages[0]}"
    return messages[0]["result"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_has_mode_hook() -> None:
    """describe must report a hook that handles 'tool:pre' and 'provider:request' events."""
    result = await _send_describe()
    caps = result["capabilities"]

    hooks = caps.get("hooks", [])
    assert len(hooks) >= 1, f"Expected at least 1 hook, got: {hooks}"

    # Find a hook that covers both required events
    mode_hook = None
    for hook in hooks:
        events = set(hook.get("events", []))
        if "tool:pre" in events and "provider:request" in events:
            mode_hook = hook
            break

    assert mode_hook is not None, (
        f"Expected a hook with events containing 'tool:pre' and 'provider:request'. "
        f"Found hooks: {hooks}"
    )


@pytest.mark.asyncio
async def test_describe_has_mode_tool() -> None:
    """describe must report the 'mode' tool."""
    result = await _send_describe()
    caps = result["capabilities"]

    tools = caps.get("tools", [])
    names = [t["name"] for t in tools]
    assert "mode" in names, f"Expected 'mode' in tools; found: {names}"


@pytest.mark.asyncio
async def test_describe_mode_tool_has_schema() -> None:
    """The 'mode' tool must have an input_schema with 'operation' as a required enum field."""
    result = await _send_describe()
    caps = result["capabilities"]

    tools = caps.get("tools", [])
    mode_tool = next((t for t in tools if t["name"] == "mode"), None)
    assert mode_tool is not None, "Expected 'mode' tool in describe output"

    schema = mode_tool.get("input_schema", {})
    props = schema.get("properties", {})
    assert "operation" in props, f"Expected 'operation' in schema properties: {props}"

    operation_schema = props["operation"]
    assert "enum" in operation_schema, (
        f"Expected 'enum' in operation schema: {operation_schema}"
    )
    ops = set(operation_schema["enum"])
    assert ops == {"set", "clear", "list", "current"}, (
        f"Expected operations {{set, clear, list, current}}, got: {ops}"
    )

    required = schema.get("required", [])
    assert "operation" in required, f"Expected 'operation' to be required: {required}"


@pytest.mark.asyncio
async def test_describe_has_content_paths() -> None:
    """describe must report >= 2 content paths including behaviors and context files."""
    result = await _send_describe()
    caps = result["capabilities"]

    paths = caps.get("content", {}).get("paths", [])
    assert len(paths) >= 2, f"Expected >= 2 content paths, got {len(paths)}: {paths}"

    behaviors = [p for p in paths if p.startswith("behaviors/")]
    context = [p for p in paths if p.startswith("context/")]

    assert len(behaviors) >= 1, (
        f"Expected >= 1 behavior content path, got {len(behaviors)}: {behaviors}"
    )
    assert len(context) >= 1, (
        f"Expected >= 1 context content path, got {len(context)}: {context}"
    )


@pytest.mark.asyncio
async def test_describe_content_includes_modes_yaml() -> None:
    """describe must report 'behaviors/modes.yaml' in content paths."""
    result = await _send_describe()
    caps = result["capabilities"]

    paths = caps.get("content", {}).get("paths", [])
    assert "behaviors/modes.yaml" in paths, (
        f"Expected 'behaviors/modes.yaml' in content paths, got: {paths}"
    )


@pytest.mark.asyncio
async def test_describe_content_includes_modes_instructions() -> None:
    """describe must report 'context/modes-instructions.md' in content paths."""
    result = await _send_describe()
    caps = result["capabilities"]

    paths = caps.get("content", {}).get("paths", [])
    assert "context/modes-instructions.md" in paths, (
        f"Expected 'context/modes-instructions.md' in content paths, got: {paths}"
    )
