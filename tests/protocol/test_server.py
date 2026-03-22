"""Tests for the generic JSON-RPC 2.0 server and content.py."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from amplifier_ipc.protocol.server import Server


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
        "from amplifier_ipc.protocol.decorators import tool\n\n"
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
        "from amplifier_ipc.protocol.decorators import tool\n"
        "from amplifier_ipc.protocol.models import ToolResult\n\n"
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


async def test_context_manager_add_and_get_messages(tmp_path: Path) -> None:
    """context.add_message stores a message; context.get_messages returns it.

    The server must dispatch context.add_message and context.get_messages
    to the registered context manager component.
    """
    pkg_name = "mock_ctx_pkg"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)

    ctx_dir = pkg_dir / "context_managers"
    ctx_dir.mkdir()
    (ctx_dir / "__init__.py").write_text("")
    (ctx_dir / "mem_ctx.py").write_text(
        "from amplifier_ipc.protocol.decorators import context_manager\n"
        "from amplifier_ipc.protocol.models import Message\n"
        "from typing import Any\n\n"
        "@context_manager\n"
        "class MemContextManager:\n"
        "    name = 'mem'\n"
        "    def __init__(self):\n"
        "        self._messages = []\n"
        "    async def add_message(self, message: Message) -> None:\n"
        "        self._messages.append(message)\n"
        "    async def get_messages(self, provider_info: dict) -> list:\n"
        "        return [m.model_dump() for m in self._messages]\n"
        "    async def clear(self) -> None:\n"
        "        self._messages = []\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        responses = await _send_and_collect(
            server,
            [
                {
                    "jsonrpc": "2.0",
                    "id": 10,
                    "method": "context.add_message",
                    "params": {"message": {"role": "user", "content": "hello"}},
                },
                {
                    "jsonrpc": "2.0",
                    "id": 11,
                    "method": "context.get_messages",
                    "params": {},
                },
            ],
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)

    assert len(responses) == 2
    assert "result" in responses[0], f"add_message failed: {responses[0]}"
    assert "result" in responses[1], f"get_messages failed: {responses[1]}"
    messages = responses[1]["result"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "hello"


async def test_provider_complete_dispatches_to_provider(tmp_path: Path) -> None:
    """provider.complete calls the registered provider's complete() method."""
    pkg_name = "mock_provider_pkg"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)

    prov_dir = pkg_dir / "providers"
    prov_dir.mkdir()
    (prov_dir / "__init__.py").write_text("")
    (prov_dir / "echo_prov.py").write_text(
        "from amplifier_ipc.protocol.decorators import provider\n"
        "from amplifier_ipc.protocol.models import ChatRequest, ChatResponse\n\n"
        "@provider\n"
        "class EchoProvider:\n"
        "    name = 'echo'\n"
        "    async def complete(self, request: ChatRequest, **kwargs) -> ChatResponse:\n"
        "        return ChatResponse(content='echo', tool_calls=[])\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        responses = await _send_and_collect(
            server,
            [
                {
                    "jsonrpc": "2.0",
                    "id": 20,
                    "method": "provider.complete",
                    "params": {
                        "request": {
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "hi",
                                    "tool_calls": [],
                                    "tool_results": [],
                                }
                            ],
                            "tools": None,
                            "reasoning_effort": None,
                        }
                    },
                }
            ],
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)

    assert len(responses) == 1
    assert "result" in responses[0], f"provider.complete failed: {responses[0]}"
    result = responses[0]["result"]
    assert result["content"] == "echo"


async def test_orchestrator_execute_dispatches_to_orchestrator(
    tmp_path: Path,
) -> None:
    """orchestrator.execute calls the registered orchestrator's execute() method.

    The orchestrator receives the prompt, config (with system_prompt), and a client
    that it can use to make requests back to the host.  The server returns whatever
    execute() returns as the JSON-RPC response result.
    """
    pkg_name = "mock_orch_pkg_exec"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)

    # Create an orchestrators/ sub-package with a minimal orchestrator
    orch_dir = pkg_dir / "orchestrators"
    orch_dir.mkdir()
    (orch_dir / "__init__.py").write_text("")
    (orch_dir / "simple_orch.py").write_text(
        "from amplifier_ipc.protocol.decorators import orchestrator\n"
        "from typing import Any\n\n"
        "@orchestrator\n"
        "class SimpleOrchestrator:\n"
        "    name = 'simple'\n"
        "    async def execute(self, prompt: str, config: dict, client: Any) -> str:\n"
        "        return f'Echo: {prompt}'\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        responses = await _send_and_collect(
            server,
            [
                {
                    "jsonrpc": "2.0",
                    "id": 99,
                    "method": "orchestrator.execute",
                    "params": {"prompt": "hello world", "system_prompt": "be helpful"},
                }
            ],
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)

    assert len(responses) == 1
    assert "result" in responses[0], f"Expected result, got: {responses[0]}"
    assert responses[0]["result"] == "Echo: hello world"


# ---------------------------------------------------------------------------
# Task-12: Lazy instantiation & configure tests
# ---------------------------------------------------------------------------


async def test_server_describe_before_configure(tmp_path: Path) -> None:
    """describe works without calling configure, using class metadata."""
    pkg_name = "mock_srv_pre_configure_pkg"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)
    tools_dir = pkg_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "mytool.py").write_text(
        "from amplifier_ipc.protocol.decorators import tool\n\n"
        "@tool\n"
        "class MyTool:\n"
        "    name = 'mytool'\n"
        "    description = 'A test tool'\n"
        "    input_schema = {'type': 'object'}\n"
        "    async def execute(self, input):\n"
        "        return 'ok'\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        # Do NOT call configure - describe should work from class metadata
        assert server._instances_ready is False, (
            "instances should not be ready before configure"
        )
        responses = await _send_and_collect(
            server,
            [{"jsonrpc": "2.0", "id": 1, "method": "describe"}],
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)

    result = responses[0]["result"]
    tools = result["capabilities"]["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "mytool"
    assert tools[0]["description"] == "A test tool"
    assert tools[0]["input_schema"] == {"type": "object"}


async def test_server_configure_instantiates_with_config(tmp_path: Path) -> None:
    """configure instantiates tools with provided config when config is available."""
    pkg_name = "mock_srv_configure_config_pkg"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)
    tools_dir = pkg_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "configtool.py").write_text(
        "from amplifier_ipc.protocol.decorators import tool\n\n"
        "@tool\n"
        "class ConfigTool:\n"
        "    name = 'configtool'\n"
        "    description = 'A configurable tool'\n"
        "    input_schema = {}\n"
        "    def __init__(self, config=None):\n"
        "        self.config = config\n"
        "    async def execute(self, input):\n"
        "        return self.config\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        assert server._instances_ready is False

        result = await server.handle_configure(
            {"config": {"configtool": {"key": "value"}}}
        )
        assert result == {"status": "ok"}
        assert server._instances_ready is True
        assert len(server._tool_instances) == 1
        assert server._tool_instances[0].config == {"key": "value"}
    finally:
        _cleanup_package(tmp_path, pkg_name)


async def test_server_configure_no_config_instantiates_without_args(
    tmp_path: Path,
) -> None:
    """configure with empty config map instantiates tools with no args (cls())."""
    pkg_name = "mock_srv_configure_no_config_pkg"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)
    tools_dir = pkg_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "simpletool.py").write_text(
        "from amplifier_ipc.protocol.decorators import tool\n\n"
        "@tool\n"
        "class SimpleTool:\n"
        "    name = 'simpletool'\n"
        "    description = 'A simple tool'\n"
        "    input_schema = {}\n"
        "    async def execute(self, input):\n"
        "        return 'simple_ok'\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        assert server._instances_ready is False

        result = await server.handle_configure({})
        assert result == {"status": "ok"}
        assert server._instances_ready is True
        assert len(server._tool_instances) == 1
    finally:
        _cleanup_package(tmp_path, pkg_name)


async def test_orchestrator_can_call_local_hook_and_context(
    tmp_path: Path,
) -> None:
    """Orchestrator using client.request() for hooks/context does NOT deadlock.

    When an orchestrator calls request.hook_emit or request.context_* via its
    client, the server handles these locally (without going through IPC), so
    the server's own handle_stream() loop does not need to be running concurrently.
    This avoids the deadlock that would occur if those calls were routed back to
    the same service over IPC.
    """
    pkg_name = "mock_orch_local_pkg"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)

    orch_dir = pkg_dir / "orchestrators"
    orch_dir.mkdir()
    (orch_dir / "__init__.py").write_text("")
    (orch_dir / "local_orch.py").write_text(
        "from amplifier_ipc.protocol.decorators import orchestrator\n"
        "from typing import Any\n\n"
        "@orchestrator\n"
        "class LocalOrchestrator:\n"
        "    name = 'local'\n"
        "    async def execute(self, prompt: str, config: dict, client: Any) -> str:\n"
        "        # Add a context message\n"
        "        await client.request('request.context_add_message', {'message': {'role': 'user', 'content': prompt}})\n"
        "        # Retrieve messages\n"
        "        msgs = await client.request('request.context_get_messages', {})\n"
        "        count = len(msgs) if msgs else 0\n"
        "        # Emit a hook (handled locally)\n"
        "        await client.request('request.hook_emit', {'event': 'prompt:submit', 'data': {'prompt': prompt}})\n"
        "        return f'processed {count} messages'\n"
    )

    ctx_dir = pkg_dir / "context_managers"
    ctx_dir.mkdir()
    (ctx_dir / "__init__.py").write_text("")
    (ctx_dir / "mem.py").write_text(
        "from amplifier_ipc.protocol.decorators import context_manager\n"
        "from amplifier_ipc.protocol.models import Message\n"
        "from typing import Any\n\n"
        "@context_manager\n"
        "class Mem:\n"
        "    name = 'mem'\n"
        "    def __init__(self): self._messages = []\n"
        "    async def add_message(self, message: Message): self._messages.append(message)\n"
        "    async def get_messages(self, pi: dict): return [m.model_dump() for m in self._messages]\n"
        "    async def clear(self): self._messages = []\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        responses = await _send_and_collect(
            server,
            [
                {
                    "jsonrpc": "2.0",
                    "id": 77,
                    "method": "orchestrator.execute",
                    "params": {"prompt": "hello", "system_prompt": ""},
                }
            ],
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)

    assert len(responses) == 1
    assert "result" in responses[0], f"Expected result, got: {responses[0]}"
    # The orchestrator added 1 message before calling get_messages
    assert responses[0]["result"] == "processed 1 messages"
