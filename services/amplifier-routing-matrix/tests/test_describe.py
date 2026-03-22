"""Service describe verification — verifies the full service starts, responds to
describe, and reports all components correctly.

Uses a real Server('amplifier_routing_matrix') instance (no mock package) to exercise
the live discovery path end-to-end.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from amplifier_ipc.protocol.server import Server


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
    """Create Server('amplifier_routing_matrix'), send a describe request, return result.

    Sends one JSON-RPC describe request over an asyncio.StreamReader, collects the
    response via _MockWriter, and returns the ``result`` dict from the response.
    """
    server = Server("amplifier_routing_matrix")
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
# Hook tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_has_exactly_one_hook() -> None:
    """describe must report exactly 1 hook (RoutingHook)."""
    result = await _send_describe()
    caps = result["capabilities"]

    hooks = caps.get("hooks", [])
    assert len(hooks) == 1, f"Expected exactly 1 hook, got: {hooks}"


@pytest.mark.asyncio
async def test_describe_routing_hook_events() -> None:
    """The routing hook must handle 'session:start' and 'provider:request' events."""
    result = await _send_describe()
    caps = result["capabilities"]

    hooks = caps.get("hooks", [])
    assert len(hooks) >= 1, f"Expected at least 1 hook, got: {hooks}"

    routing_hook = hooks[0]
    events = set(routing_hook.get("events", []))

    assert "session:start" in events, (
        f"Expected 'session:start' in hook events, got: {events}"
    )
    assert "provider:request" in events, (
        f"Expected 'provider:request' in hook events, got: {events}"
    )


@pytest.mark.asyncio
async def test_describe_routing_hook_name() -> None:
    """The routing hook must be named 'routing_hook'."""
    result = await _send_describe()
    caps = result["capabilities"]

    hooks = caps.get("hooks", [])
    assert len(hooks) >= 1, f"Expected at least 1 hook, got: {hooks}"

    routing_hook = hooks[0]
    assert routing_hook.get("name") == "routing_hook", (
        f"Expected hook name 'routing_hook', got: {routing_hook.get('name')}"
    )


@pytest.mark.asyncio
async def test_describe_routing_hook_priority() -> None:
    """The routing hook must have priority 5."""
    result = await _send_describe()
    caps = result["capabilities"]

    hooks = caps.get("hooks", [])
    assert len(hooks) >= 1, f"Expected at least 1 hook, got: {hooks}"

    routing_hook = hooks[0]
    assert routing_hook.get("priority") == 5, (
        f"Expected hook priority 5, got: {routing_hook.get('priority')}"
    )


# ---------------------------------------------------------------------------
# No tools / orchestrators / context_managers / providers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_has_no_tools() -> None:
    """describe must report 0 tools — the routing service has hooks only."""
    result = await _send_describe()
    caps = result["capabilities"]

    tools = caps.get("tools", [])
    assert len(tools) == 0, f"Expected 0 tools, got: {tools}"


@pytest.mark.asyncio
async def test_describe_has_no_orchestrators() -> None:
    """describe must report 0 orchestrators."""
    result = await _send_describe()
    caps = result["capabilities"]

    orchestrators = caps.get("orchestrators", [])
    assert len(orchestrators) == 0, f"Expected 0 orchestrators, got: {orchestrators}"


@pytest.mark.asyncio
async def test_describe_has_no_context_managers() -> None:
    """describe must report 0 context_managers."""
    result = await _send_describe()
    caps = result["capabilities"]

    context_managers = caps.get("context_managers", [])
    assert len(context_managers) == 0, (
        f"Expected 0 context_managers, got: {context_managers}"
    )


@pytest.mark.asyncio
async def test_describe_has_no_providers() -> None:
    """describe must report 0 providers."""
    result = await _send_describe()
    caps = result["capabilities"]

    providers = caps.get("providers", [])
    assert len(providers) == 0, f"Expected 0 providers, got: {providers}"


# ---------------------------------------------------------------------------
# Content paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_has_content_paths() -> None:
    """describe must report content paths."""
    result = await _send_describe()
    caps = result["capabilities"]

    paths = caps.get("content", {}).get("paths", [])
    assert len(paths) >= 1, f"Expected >= 1 content path, got {len(paths)}: {paths}"


@pytest.mark.asyncio
async def test_describe_content_includes_context_paths() -> None:
    """describe must report context/ paths in content."""
    result = await _send_describe()
    caps = result["capabilities"]

    paths = caps.get("content", {}).get("paths", [])
    context_paths = [p for p in paths if p.startswith("context/")]
    assert len(context_paths) >= 1, (
        f"Expected >= 1 context/ content path, got {len(context_paths)}: {context_paths}"
    )


@pytest.mark.asyncio
async def test_describe_content_includes_routing_instructions() -> None:
    """describe must report 'context/routing-instructions.md' in content paths."""
    result = await _send_describe()
    caps = result["capabilities"]

    paths = caps.get("content", {}).get("paths", [])
    assert "context/routing-instructions.md" in paths, (
        f"Expected 'context/routing-instructions.md' in content paths, got: {paths}"
    )


@pytest.mark.asyncio
async def test_describe_content_includes_role_definitions() -> None:
    """describe must report 'context/role-definitions.md' in content paths."""
    result = await _send_describe()
    caps = result["capabilities"]

    paths = caps.get("content", {}).get("paths", [])
    assert "context/role-definitions.md" in paths, (
        f"Expected 'context/role-definitions.md' in content paths, got: {paths}"
    )
