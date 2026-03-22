"""Service describe verification — verifies the full service starts, responds to
describe, and reports all components correctly.

Uses a real Server('amplifier_foundation') instance (no mock package) to exercise
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
    """Create Server('amplifier_foundation'), send a describe request, return result.

    Sends one JSON-RPC describe request over an asyncio.StreamReader, collects the
    response via _MockWriter, and returns the ``result`` dict from the response.
    """
    server = Server("amplifier_foundation")
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
async def test_describe_has_orchestrator() -> None:
    """describe must report the 'streaming' orchestrator."""
    result = await _send_describe()
    caps = result["capabilities"]

    orchestrators = caps.get("orchestrators", [])
    names = [o["name"] for o in orchestrators]
    assert "streaming" in names, (
        f"Expected 'streaming' in orchestrators; found: {names}"
    )


@pytest.mark.asyncio
async def test_describe_has_context_manager() -> None:
    """describe must report the 'simple' context manager."""
    result = await _send_describe()
    caps = result["capabilities"]

    context_managers = caps.get("context_managers", [])
    names = [cm["name"] for cm in context_managers]
    assert "simple" in names, f"Expected 'simple' in context_managers; found: {names}"


@pytest.mark.asyncio
async def test_describe_has_tools() -> None:
    """describe must report >=10 tools including the core set."""
    result = await _send_describe()
    caps = result["capabilities"]

    tools = caps.get("tools", [])
    names = {t["name"] for t in tools}

    assert len(tools) >= 10, f"Expected >= 10 tools, got {len(tools)}: {sorted(names)}"

    required = {
        "bash",
        "todo",
        "read_file",
        "write_file",
        "edit_file",
        "grep",
        "glob",
        "web_search",
        "web_fetch",
    }
    missing = required - names
    assert not missing, (
        f"Missing required tools: {sorted(missing)}. Found: {sorted(names)}"
    )


@pytest.mark.asyncio
async def test_describe_has_hooks() -> None:
    """describe must report >= 10 hooks."""
    result = await _send_describe()
    caps = result["capabilities"]

    hooks = caps.get("hooks", [])
    assert len(hooks) >= 10, (
        f"Expected >= 10 hooks, got {len(hooks)}: {[h['name'] for h in hooks]}"
    )


@pytest.mark.asyncio
async def test_describe_has_content() -> None:
    """describe must report >=20 content paths with >=5 behaviors and >=5 context.

    Note: agent definitions (formerly 'sessions') live at the service root as fsspec
    URIs and are NOT served as package content. Only behaviors, context, and recipes
    are served via content.read/content.list.
    """
    result = await _send_describe()
    caps = result["capabilities"]

    paths = caps.get("content", {}).get("paths", [])
    assert len(paths) >= 20, f"Expected >= 20 content paths, got {len(paths)}"

    behaviors = [p for p in paths if p.startswith("behaviors/")]
    context = [p for p in paths if p.startswith("context/")]

    assert len(behaviors) >= 5, (
        f"Expected >= 5 behavior content paths, got {len(behaviors)}: {behaviors}"
    )
    assert len(context) >= 5, (
        f"Expected >= 5 context content paths, got {len(context)}: {context}"
    )
