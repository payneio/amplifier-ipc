"""Integration tests: real mock service subprocess spawned and communicated with.

Proves the full stack works end-to-end using a real OS subprocess:
  spawn -> describe -> tool.execute -> content.read -> shutdown
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from amplifier_ipc_host.lifecycle import ServiceProcess, shutdown_service
from amplifier_ipc_host.registry import CapabilityRegistry
from amplifier_ipc_protocol.client import Client

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

# The amplifier-ipc-protocol source lives alongside amplifier-ipc-host
_PROTOCOL_SRC = Path(__file__).parent.parent.parent / "amplifier-ipc-protocol" / "src"


# ---------------------------------------------------------------------------
# Mock service package builder
# ---------------------------------------------------------------------------


def _create_mock_service_package(tmp_path: Path) -> Path:
    """Create a real Python mock_service package under *tmp_path* and return *tmp_path*.

    Package layout::

        tmp_path/
          mock_service/
            __init__.py           (empty)
            __main__.py           (Server("mock_service").run())
            tools/
              __init__.py         (empty)
              echo.py             (@tool EchoTool returning ToolResult)
            agents/
              test_agent.md       (# Test Agent)
            context/
              test_context.md     (Test context content.)

    Returns:
        *tmp_path* (the parent directory of the mock_service package).
    """
    pkg = tmp_path / "mock_service"
    pkg.mkdir()

    # Package init
    (pkg / "__init__.py").write_text("")

    # __main__.py — entry point for `python -m mock_service`
    (pkg / "__main__.py").write_text(
        "from amplifier_ipc_protocol.server import Server\n"
        'Server("mock_service").run()\n'
    )

    # tools/
    tools_dir = pkg / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "echo.py").write_text(
        "from amplifier_ipc_protocol.decorators import tool\n"
        "from amplifier_ipc_protocol.models import ToolResult\n"
        "\n"
        "@tool\n"
        "class EchoTool:\n"
        '    name = "echo"\n'
        '    description = "Echoes back the input text"\n'
        "    input_schema = {\n"
        '        "type": "object",\n'
        '        "properties": {"text": {"type": "string"}},\n'
        "    }\n"
        "\n"
        "    async def execute(self, input):\n"
        '        return ToolResult(success=True, output=input.get("text", ""))\n'
    )

    # agents/
    agents_dir = pkg / "agents"
    agents_dir.mkdir()
    (agents_dir / "test_agent.md").write_text("# Test Agent")

    # context/
    context_dir = pkg / "context"
    context_dir.mkdir()
    (context_dir / "test_context.md").write_text("Test context content.")

    return tmp_path


def _build_subprocess_env(pkg_parent: Path) -> dict[str, str]:
    """Build environment dict with PYTHONPATH including pkg_parent and protocol src."""
    existing = os.environ.get("PYTHONPATH", "")
    extra_paths = [str(pkg_parent), str(_PROTOCOL_SRC)]
    if existing:
        extra_paths.append(existing)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(extra_paths)
    return env


async def _spawn_mock_service(pkg_parent: Path) -> ServiceProcess:
    """Spawn mock_service subprocess with custom PYTHONPATH and return a ServiceProcess."""
    env = _build_subprocess_env(pkg_parent)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mock_service",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    assert process.stdout is not None
    assert process.stdin is not None
    client = Client(reader=process.stdout, writer=process.stdin)
    return ServiceProcess(name="mock", process=process, client=client)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


async def test_spawn_describe_and_teardown(tmp_path: Path) -> None:
    """Spawn real mock service, interact with it, then shut it down."""
    pkg_parent = _create_mock_service_package(tmp_path)
    service = await _spawn_mock_service(pkg_parent)

    try:
        client = service.client

        # --- describe ---
        describe_result = await client.request("describe")

        assert describe_result["name"] == "mock_service"

        caps = describe_result["capabilities"]
        tool_names = [t["name"] for t in caps["tools"]]
        assert "echo" in tool_names

        content_paths = caps["content"]["paths"]
        assert "agents/test_agent.md" in content_paths
        assert "context/test_context.md" in content_paths

        # --- tool.execute ---
        tool_result = await client.request(
            "tool.execute",
            {"name": "echo", "input": {"text": "hello"}},
        )
        assert tool_result["success"] is True
        assert tool_result["output"] == "hello"

        # --- content.read ---
        content_result = await client.request(
            "content.read",
            {"path": "context/test_context.md"},
        )
        assert content_result["content"] == "Test context content."

    finally:
        await shutdown_service(service, timeout=5.0)

    assert service.process.returncode is not None


async def test_registry_from_real_service(tmp_path: Path) -> None:
    """Spawn real mock service, build CapabilityRegistry from describe, verify lookups."""
    pkg_parent = _create_mock_service_package(tmp_path)
    service = await _spawn_mock_service(pkg_parent)

    try:
        client = service.client

        # --- describe ---
        describe_result = await client.request("describe")

        # Transform server's nested capabilities format into the flat format
        # that CapabilityRegistry.register() expects
        caps = describe_result.get("capabilities", {})
        flat_describe = {
            "tools": caps.get("tools", []),
            "hooks": caps.get("hooks", []),
            "orchestrators": caps.get("orchestrators", []),
            "context_managers": caps.get("context_managers", []),
            "providers": caps.get("providers", []),
            "content": caps.get("content", {}).get("paths", []),
        }

        registry = CapabilityRegistry()
        registry.register("mock", flat_describe)

        # --- verify registry lookups ---
        assert registry.get_tool_service("echo") == "mock"

        all_specs = registry.get_all_tool_specs()
        spec_names = [s["name"] for s in all_specs]
        assert "echo" in spec_names

        content = registry.get_content_services()
        assert "mock" in content
        assert "agents/test_agent.md" in content["mock"]

    finally:
        await shutdown_service(service, timeout=5.0)
