"""Integration tests: Client + Server communicating over asyncio pipes.

Proves the full stack works end-to-end using in-process asyncio pipes,
so no real OS sockets or subprocesses are required.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from amplifier_ipc.protocol.client import Client
from amplifier_ipc.protocol.server import Server


# ---------------------------------------------------------------------------
# Infrastructure: in-process pipe helpers
# ---------------------------------------------------------------------------


class PipeWriter:
    """Writer that feeds bytes directly into a StreamReader (in-process pipe).

    Used to connect Client and Server over an asyncio pipe without OS sockets.
    ``write()`` calls ``reader.feed_data()``; ``drain()`` is a no-op.
    """

    def __init__(self, reader: asyncio.StreamReader) -> None:
        self._reader = reader

    def write(self, data: bytes) -> None:
        self._reader.feed_data(data)

    async def drain(self) -> None:
        pass  # no-op for in-process pipes


def _create_connected_pair() -> tuple[
    asyncio.StreamReader,
    PipeWriter,
    asyncio.StreamReader,
    PipeWriter,
]:
    """Create a connected (client, server) asyncio pipe pair.

    Returns:
        (client_reader, client_writer, server_reader, server_writer)

    Data flow:
        client_writer  →  server_reader   (client → server)
        server_writer  →  client_reader   (server → client)
    """
    client_reader = asyncio.StreamReader()
    server_reader = asyncio.StreamReader()
    # client_writer feeds into server_reader
    client_writer = PipeWriter(server_reader)
    # server_writer feeds into client_reader
    server_writer = PipeWriter(client_reader)
    return client_reader, client_writer, server_reader, server_writer


# ---------------------------------------------------------------------------
# Package helpers
# ---------------------------------------------------------------------------

_ADDER_SOURCE = (
    "from amplifier_ipc.protocol.decorators import tool\n\n"
    "@tool\n"
    "class AdderTool:\n"
    "    name = 'adder'\n"
    "    description = 'Adds two numbers'\n"
    "    input_schema = {'type': 'object'}\n\n"
    "    async def execute(self, input):\n"
    "        return input['a'] + input['b']\n"
)


def _make_pkg(tmp_path: Path, pkg_name: str) -> Path:
    """Create a minimal mock package directory and return it."""
    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir(exist_ok=True)
    (pkg_dir / "__init__.py").write_text("")
    return pkg_dir


def _add_adder_tool(pkg_dir: Path) -> None:
    """Add a tools/adder.py tool to *pkg_dir*."""
    tools_dir = pkg_dir / "tools"
    tools_dir.mkdir(exist_ok=True)
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "adder.py").write_text(_ADDER_SOURCE)


def _add_content(pkg_dir: Path) -> None:
    """Add an agents/explorer.md content file to *pkg_dir*."""
    agents_dir = pkg_dir / "agents"
    agents_dir.mkdir(exist_ok=True)
    (agents_dir / "explorer.md").write_text("# Explorer Agent")


def _cleanup_pkg(tmp_path: Path, pkg_name: str) -> None:
    """Remove pkg from sys.path and sys.modules."""
    try:
        sys.path.remove(str(tmp_path))
    except ValueError:
        pass
    for key in list(sys.modules.keys()):
        if key == pkg_name or key.startswith(f"{pkg_name}."):
            del sys.modules[key]


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_server_describe(tmp_path: Path) -> None:
    """Client sends describe to Server; gets capabilities with tool name and content paths back."""
    pkg_name = "mock_integ_describe_pkg"
    pkg_dir = _make_pkg(tmp_path, pkg_name)
    _add_adder_tool(pkg_dir)
    _add_content(pkg_dir)

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        client_reader, client_writer, server_reader, server_writer = (
            _create_connected_pair()
        )

        server_task = asyncio.create_task(
            server.handle_stream(server_reader, server_writer)
        )

        client = Client(client_reader, client_writer)
        result = await asyncio.wait_for(client.request("describe"), timeout=2.0)

        # Clean shutdown: signal EOF to server and wait for it to finish
        server_reader.feed_eof()
        await asyncio.wait_for(server_task, timeout=2.0)
    finally:
        _cleanup_pkg(tmp_path, pkg_name)

    assert result["name"] == pkg_name
    caps = result["capabilities"]
    tool_names = [t["name"] for t in caps["tools"]]
    assert "adder" in tool_names
    content_paths = caps["content"]["paths"]
    assert "agents/explorer.md" in content_paths


@pytest.mark.asyncio
async def test_client_server_tool_execute(tmp_path: Path) -> None:
    """Client executes adder tool (a=10, b=32), gets {success: True, output: 42}."""
    pkg_name = "mock_integ_execute_pkg"
    pkg_dir = _make_pkg(tmp_path, pkg_name)
    _add_adder_tool(pkg_dir)

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        client_reader, client_writer, server_reader, server_writer = (
            _create_connected_pair()
        )

        server_task = asyncio.create_task(
            server.handle_stream(server_reader, server_writer)
        )

        client = Client(client_reader, client_writer)
        result = await asyncio.wait_for(
            client.request(
                "tool.execute",
                {"name": "adder", "input": {"a": 10, "b": 32}},
            ),
            timeout=2.0,
        )

        server_reader.feed_eof()
        await asyncio.wait_for(server_task, timeout=2.0)
    finally:
        _cleanup_pkg(tmp_path, pkg_name)

    assert result["success"] is True
    assert result["output"] == 42


@pytest.mark.asyncio
async def test_client_server_content_read(tmp_path: Path) -> None:
    """Client reads agents/explorer.md content through Server."""
    pkg_name = "mock_integ_content_pkg"
    pkg_dir = _make_pkg(tmp_path, pkg_name)
    _add_content(pkg_dir)

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        client_reader, client_writer, server_reader, server_writer = (
            _create_connected_pair()
        )

        server_task = asyncio.create_task(
            server.handle_stream(server_reader, server_writer)
        )

        client = Client(client_reader, client_writer)
        result = await asyncio.wait_for(
            client.request("content.read", {"path": "agents/explorer.md"}),
            timeout=2.0,
        )

        server_reader.feed_eof()
        await asyncio.wait_for(server_task, timeout=2.0)
    finally:
        _cleanup_pkg(tmp_path, pkg_name)

    assert result["content"] == "# Explorer Agent"


@pytest.mark.asyncio
async def test_client_server_multiple_requests(tmp_path: Path) -> None:
    """Client sends 3 sequential requests (describe, tool.execute, content.list) over one connection."""
    pkg_name = "mock_integ_multi_pkg"
    pkg_dir = _make_pkg(tmp_path, pkg_name)
    _add_adder_tool(pkg_dir)
    _add_content(pkg_dir)

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        client_reader, client_writer, server_reader, server_writer = (
            _create_connected_pair()
        )

        server_task = asyncio.create_task(
            server.handle_stream(server_reader, server_writer)
        )

        client = Client(client_reader, client_writer)

        # Request 1: describe
        describe_result = await asyncio.wait_for(
            client.request("describe"), timeout=2.0
        )

        # Request 2: tool.execute
        execute_result = await asyncio.wait_for(
            client.request(
                "tool.execute",
                {"name": "adder", "input": {"a": 5, "b": 7}},
            ),
            timeout=2.0,
        )

        # Request 3: content.list
        list_result = await asyncio.wait_for(
            client.request("content.list"), timeout=2.0
        )

        server_reader.feed_eof()
        await asyncio.wait_for(server_task, timeout=2.0)
    finally:
        _cleanup_pkg(tmp_path, pkg_name)

    # Verify describe
    assert describe_result["name"] == pkg_name
    tool_names = [t["name"] for t in describe_result["capabilities"]["tools"]]
    assert "adder" in tool_names

    # Verify tool execute
    assert execute_result["success"] is True
    assert execute_result["output"] == 12

    # Verify content list
    assert "agents/explorer.md" in list_result["paths"]
