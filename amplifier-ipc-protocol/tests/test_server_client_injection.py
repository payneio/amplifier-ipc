"""Tests for orchestrator client injection into tools.

Verifies that when a tool with a 'client' attribute is executed while an
orchestrator is running, the orchestrator's IPC client is injected into the
tool before execute() is called.
"""

from __future__ import annotations

import sys
from pathlib import Path

from amplifier_ipc_protocol.server import Server


# ---------------------------------------------------------------------------
# Helpers (copied from test_server.py pattern)
# ---------------------------------------------------------------------------


def _create_mock_package(tmp_path: Path, pkg_name: str) -> Path:
    """Create a minimal mock package in tmp_path and return its directory."""
    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir(exist_ok=True)
    (pkg_dir / "__init__.py").write_text("")
    return pkg_dir


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


async def test_tool_receives_orchestrator_client(tmp_path: Path) -> None:
    """Tool with 'client' attribute gets orchestrator client injected before execute().

    When _current_orchestrator_client is set on the server (i.e., an orchestrator
    is running), and a tool with a 'client' attribute is executed via
    _handle_tool_execute, the tool's client attribute should be set to the
    orchestrator's client before execute() is called.
    """
    pkg_name = "mock_client_injection_pkg"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)
    tools_dir = pkg_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "client_tool.py").write_text(
        "from amplifier_ipc_protocol.decorators import tool\n\n"
        "@tool\n"
        "class ClientTool:\n"
        "    name = 'client_tool'\n"
        "    description = 'Test tool with client'\n"
        "    input_schema = {}\n"
        "    client = None\n"
        "    client_at_execute_time = None\n\n"
        "    async def execute(self, input):\n"
        "        self.client_at_execute_time = self.client\n"
        "        return 'ok'\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)

        # Simulate an active orchestrator client (as would be set by
        # _handle_orchestrator_execute before calling orch_instance.execute())
        mock_client = object()
        server._current_orchestrator_client = mock_client

        # Execute the tool (as would happen when orchestrator calls tool via
        # request.tool_execute -> _handle_tool_execute)
        await server._handle_tool_execute({"name": "client_tool", "input": {}})

        # Verify the tool's client was set to the orchestrator client before execute()
        tool_instance = server._tools["client_tool"]
        assert tool_instance.client_at_execute_time is mock_client, (
            "Tool's client attribute should have been set to the orchestrator "
            f"client before execute(), got: {tool_instance.client_at_execute_time!r}"
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)


async def test_tool_without_client_attr_unaffected(tmp_path: Path) -> None:
    """Tool without a 'client' attribute is not affected by client injection.

    If a tool does not have a 'client' attribute, _handle_tool_execute should
    not attempt to set one (no AttributeError should be raised).
    """
    pkg_name = "mock_no_client_pkg"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)
    tools_dir = pkg_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "plain_tool.py").write_text(
        "from amplifier_ipc_protocol.decorators import tool\n\n"
        "@tool\n"
        "class PlainTool:\n"
        "    name = 'plain_tool'\n"
        "    description = 'Test tool without client'\n"
        "    input_schema = {}\n\n"
        "    async def execute(self, input):\n"
        "        return 'ok'\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        # Set an orchestrator client - should not affect tools without client attr
        server._current_orchestrator_client = object()

        # Should not raise any exception
        result = await server._handle_tool_execute({"name": "plain_tool", "input": {}})
        assert result == {"success": True, "output": "ok"}
    finally:
        _cleanup_package(tmp_path, pkg_name)


async def test_client_not_injected_when_no_orchestrator(tmp_path: Path) -> None:
    """Tool's existing client attribute is not overwritten when no orchestrator is running.

    When _current_orchestrator_client is None (outside orchestrator context),
    the tool's client attribute should remain unchanged.
    """
    pkg_name = "mock_no_orch_pkg"
    pkg_dir = _create_mock_package(tmp_path, pkg_name)
    tools_dir = pkg_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "client_tool2.py").write_text(
        "from amplifier_ipc_protocol.decorators import tool\n\n"
        "@tool\n"
        "class ClientTool2:\n"
        "    name = 'client_tool2'\n"
        "    description = 'Test tool with client'\n"
        "    input_schema = {}\n"
        "    client = None\n"
        "    client_at_execute_time = 'sentinel'\n\n"
        "    async def execute(self, input):\n"
        "        self.client_at_execute_time = self.client\n"
        "        return 'ok'\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        # No orchestrator client (None means outside orchestrator context)
        assert server._current_orchestrator_client is None

        await server._handle_tool_execute({"name": "client_tool2", "input": {}})

        tool_instance = server._tools["client_tool2"]
        # client was None, and no orchestrator client set, so client_at_execute_time
        # should be None (the value of self.client, which wasn't changed)
        assert tool_instance.client_at_execute_time is None, (
            "Tool's client should not have been modified when no orchestrator is running"
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)


async def test_current_orchestrator_client_initialized_to_none(tmp_path: Path) -> None:
    """Server.__init__ sets _current_orchestrator_client to None."""
    pkg_name = "mock_init_client_pkg"
    _create_mock_package(tmp_path, pkg_name)

    sys.path.insert(0, str(tmp_path))
    try:
        server = Server(pkg_name)
        assert hasattr(server, "_current_orchestrator_client"), (
            "Server should have _current_orchestrator_client attribute after __init__"
        )
        assert server._current_orchestrator_client is None, (
            "_current_orchestrator_client should be None initially"
        )
    finally:
        _cleanup_package(tmp_path, pkg_name)
