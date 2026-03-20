"""Tests for the generic JSON-RPC 2.0 server and content.py."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from amplifier_ipc_protocol.server import Server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockWriter:
    """Collects bytes written via write()/drain() for assertions."""

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


def _create_mock_package(tmp_path: Path, pkg_name: str) -> Path:
    """Create a minimal mock package in tmp_path and return its directory."""
    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir(exist_ok=True)
    (pkg_dir / "__init__.py").write_text("")
    return pkg_dir


async def _send_and_collect(
    server: Server,
    messages: list[dict],
) -> list[dict]:
    """Feed messages into server.handle_stream, collect and return responses."""
    reader = asyncio.StreamReader()
    writer = _MockWriter()

    for msg in messages:
        data = (json.dumps(msg) + "\n").encode()
        reader.feed_data(data)

    reader.feed_eof()
    await server.handle_stream(reader, writer)
    return writer.messages


def _cleanup_package(tmp_path: Path, pkg_name: str) -> None:
    """Remove pkg from sys.path and sys.modules."""
    try:
        sys.path.remove(str(tmp_path))
    except ValueError:
        pass
    for key in list(sys.modules.keys()):
        if key == pkg_name or key.startswith(f"{pkg_name}."):
            del sys.modules[key]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_describe_empty_package(tmp_path: Path) -> None:
    """describe returns empty capabilities for a package with no components."""
    pkg_name = "mock_srv_empty_pkg"
    _create_mock_package(tmp_path, pkg_name)
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        responses = await _send_and_collect(
            server,
            [{"jsonrpc": "2.0", "id": 1, "method": "describe"}],
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)

    assert len(responses) == 1
    assert "result" in responses[0]
    result = responses[0]["result"]
    assert result["name"] == pkg_name
    caps = result["capabilities"]
    assert caps["tools"] == []
    assert caps["hooks"] == []
    assert caps["content"]["paths"] == []


async def test_describe_with_tool(tmp_path: Path) -> None:
    """describe returns tool info in capabilities when tool is discovered."""
    pkg_name = "mock_srv_tool_pkg"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)
    tools_dir = pkg_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "echo.py").write_text(
        "from amplifier_ipc_protocol.decorators import tool\n\n"
        "@tool\n"
        "class EchoTool:\n"
        "    name = 'echo'\n"
        "    description = 'Echoes input'\n"
        "    input_schema = {'type': 'object'}\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        responses = await _send_and_collect(
            server,
            [{"jsonrpc": "2.0", "id": 1, "method": "describe"}],
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)

    result = responses[0]["result"]
    tools = result["capabilities"]["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "echo"
    assert tools[0]["description"] == "Echoes input"
    assert tools[0]["input_schema"] == {"type": "object"}


async def test_describe_with_content(tmp_path: Path) -> None:
    """describe returns content paths in capabilities."""
    pkg_name = "mock_srv_content_pkg"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)
    agents_dir = pkg_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "explorer.md").write_text("# Explorer")

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        responses = await _send_and_collect(
            server,
            [{"jsonrpc": "2.0", "id": 1, "method": "describe"}],
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)

    result = responses[0]["result"]
    paths = result["capabilities"]["content"]["paths"]
    assert "agents/explorer.md" in paths


async def test_content_read(tmp_path: Path) -> None:
    """content.read returns file content for a known path."""
    pkg_name = "mock_srv_read_pkg"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)
    agents_dir = pkg_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "explorer.md").write_text("# Explorer Agent")

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        responses = await _send_and_collect(
            server,
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "content.read",
                    "params": {"path": "agents/explorer.md"},
                }
            ],
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)

    assert len(responses) == 1
    assert "result" in responses[0]
    assert responses[0]["result"]["content"] == "# Explorer Agent"


async def test_content_read_not_found(tmp_path: Path) -> None:
    """content.read returns INVALID_PARAMS error for a missing path."""
    pkg_name = "mock_srv_nf_pkg"
    _create_mock_package(tmp_path, pkg_name)
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        responses = await _send_and_collect(
            server,
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "content.read",
                    "params": {"path": "agents/missing.md"},
                }
            ],
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)

    assert len(responses) == 1
    assert "error" in responses[0]
    assert responses[0]["error"]["code"] == -32602  # INVALID_PARAMS


async def test_content_list(tmp_path: Path) -> None:
    """content.list returns all known content paths."""
    pkg_name = "mock_srv_list_pkg"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)
    agents_dir = pkg_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "explorer.md").write_text("# Explorer")
    (agents_dir / "builder.md").write_text("# Builder")

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        responses = await _send_and_collect(
            server,
            [{"jsonrpc": "2.0", "id": 1, "method": "content.list"}],
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)

    assert len(responses) == 1
    assert "result" in responses[0]
    paths = responses[0]["result"]["paths"]
    assert "agents/explorer.md" in paths
    assert "agents/builder.md" in paths


async def test_method_not_found(tmp_path: Path) -> None:
    """Unknown method returns METHOD_NOT_FOUND (-32601) error."""
    pkg_name = "mock_srv_mnf_pkg"
    _create_mock_package(tmp_path, pkg_name)
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        responses = await _send_and_collect(
            server,
            [{"jsonrpc": "2.0", "id": 1, "method": "unknown.method"}],
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)

    assert len(responses) == 1
    assert "error" in responses[0]
    assert responses[0]["error"]["code"] == -32601  # METHOD_NOT_FOUND


async def test_tool_execute(tmp_path: Path) -> None:
    """tool.execute dispatches to the named tool and returns its result."""
    pkg_name = "mock_srv_exec_pkg"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)
    tools_dir = pkg_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "greeter.py").write_text(
        "from amplifier_ipc_protocol.decorators import tool\n"
        "from amplifier_ipc_protocol.models import ToolResult\n\n"
        "@tool\n"
        "class GreeterTool:\n"
        "    name = 'greeter'\n"
        "    description = 'Greets users'\n"
        "    input_schema = {}\n\n"
        "    async def execute(self, input):\n"
        "        return ToolResult(success=True, output='hello')\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        responses = await _send_and_collect(
            server,
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tool.execute",
                    "params": {"name": "greeter", "input": {}},
                }
            ],
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)

    assert len(responses) == 1
    assert "result" in responses[0]
    result = responses[0]["result"]
    assert result["success"] is True
    assert result["output"] == "hello"
