"""Service describe verification — verifies the full service starts, responds to
describe, and reports all components correctly.

Uses a real Server('amplifier_skills') instance (no mock package) to exercise
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
    """Create Server('amplifier_skills'), send a describe request, return result.

    Sends one JSON-RPC describe request over an asyncio.StreamReader, collects the
    response via _MockWriter, and returns the ``result`` dict from the response.
    """
    server = Server("amplifier_skills")
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
# Tool tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_has_at_least_one_tool() -> None:
    """describe must report at least 1 tool (SkillsTool / load_skill)."""
    result = await _send_describe()
    caps = result["capabilities"]

    tools = caps.get("tools", [])
    assert len(tools) >= 1, f"Expected at least 1 tool, got: {tools}"


@pytest.mark.asyncio
async def test_describe_has_load_skill_tool() -> None:
    """describe must report the 'load_skill' tool."""
    result = await _send_describe()
    caps = result["capabilities"]

    tools = caps.get("tools", [])
    names = [t["name"] for t in tools]
    assert "load_skill" in names, f"Expected 'load_skill' in tools; found: {names}"


@pytest.mark.asyncio
async def test_describe_load_skill_tool_has_schema() -> None:
    """The 'load_skill' tool must have an input_schema with expected properties."""
    result = await _send_describe()
    caps = result["capabilities"]

    tools = caps.get("tools", [])
    load_skill_tool = next((t for t in tools if t["name"] == "load_skill"), None)
    assert load_skill_tool is not None, "Expected 'load_skill' tool in describe output"

    schema = load_skill_tool.get("input_schema", {})
    props = schema.get("properties", {})

    # Must have at minimum skill_name and list properties
    assert "skill_name" in props, f"Expected 'skill_name' in schema properties: {props}"
    assert "list" in props, f"Expected 'list' in schema properties: {props}"
    assert "search" in props, f"Expected 'search' in schema properties: {props}"
    assert "info" in props, f"Expected 'info' in schema properties: {props}"


# ---------------------------------------------------------------------------
# No hooks / orchestrators / context_managers / providers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_has_no_hooks() -> None:
    """describe must report 0 hooks — the skills service has tools only."""
    result = await _send_describe()
    caps = result["capabilities"]

    hooks = caps.get("hooks", [])
    assert len(hooks) == 0, f"Expected 0 hooks, got: {hooks}"


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
async def test_describe_content_includes_skills_instructions() -> None:
    """describe must report 'context/skills-instructions.md' in content paths."""
    result = await _send_describe()
    caps = result["capabilities"]

    paths = caps.get("content", {}).get("paths", [])
    assert "context/skills-instructions.md" in paths, (
        f"Expected 'context/skills-instructions.md' in content paths, got: {paths}"
    )
