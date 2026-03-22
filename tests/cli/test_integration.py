"""Integration tests: full stack from CLI definition resolution to Host capability registry.

Proves the end-to-end data flow:
  definition resolution -> SessionConfig -> Host -> real subprocess service -> registry built.

Two integration tests:
  1. test_definition_to_session_config  — pure data pipeline, no subprocess
  2. test_host_build_registry_from_cli_definitions — real mock service subprocess
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from amplifier_ipc.host.definitions import resolve_agent
from amplifier_ipc.host.definition_registry import Registry
from amplifier_ipc.cli.session_launcher import build_session_config
from amplifier_ipc.host.config import HostSettings
from amplifier_ipc.host.host import Host
from amplifier_ipc.host.lifecycle import ServiceProcess, shutdown_service
from amplifier_ipc.protocol.client import Client

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

# Locate the amplifier-ipc root directory (parent of amplifier-ipc-cli/)
_AMPLIFIER_IPC = Path(__file__).parent.parent.parent

# amplifier-ipc unified package src
_IPC_SRC = _AMPLIFIER_IPC / "src"


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
              test.md             (# Test Agent)
            context/
              base.md             (Base context content.)

    Returns:
        *tmp_path* (the parent directory of the mock_service package).
    """
    pkg = tmp_path / "mock_service"
    pkg.mkdir()

    # Package init
    (pkg / "__init__.py").write_text("")

    # __main__.py — entry point for `python -m mock_service`
    (pkg / "__main__.py").write_text(
        "from amplifier_ipc.protocol.server import Server\n"
        'Server("mock_service").run()\n'
    )

    # tools/
    tools_dir = pkg / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "echo.py").write_text(
        "from amplifier_ipc.protocol.decorators import tool\n"
        "from amplifier_ipc.protocol.models import ToolResult\n"
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
    (agents_dir / "test.md").write_text("# Test Agent")

    # context/
    context_dir = pkg / "context"
    context_dir.mkdir()
    (context_dir / "base.md").write_text("Base context content.")

    return tmp_path


def _build_env(pkg_parent: Path) -> dict[str, str]:
    """Build environment dict with PYTHONPATH including pkg_parent and ipc src dir."""
    existing = os.environ.get("PYTHONPATH", "")
    extra_paths = [str(pkg_parent), str(_IPC_SRC)]
    if existing:
        extra_paths.append(existing)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(extra_paths)
    return env


async def _spawn_mock(pkg_parent: Path) -> ServiceProcess:
    """Spawn mock_service subprocess with custom PYTHONPATH and return a ServiceProcess."""
    env = _build_env(pkg_parent)
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
    return ServiceProcess(name="mock_service", process=process, client=client)


# ---------------------------------------------------------------------------
# Integration test 1: pure data pipeline
# ---------------------------------------------------------------------------


class TestDefinitionToSessionConfig:
    def test_definition_to_session_config(self, tmp_path: Path) -> None:
        """Pure data flow: agent YAML -> resolve_agent() -> build_session_config().

        Verifies the entire definition-to-config pipeline without spawning any
        subprocess.  Exercises:
          - Registry.register_definition() / resolve_agent()
          - definitions.resolve_agent() tree walking
          - session_launcher.build_session_config() mapping
        """
        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
type: agent
local_ref: mock-agent
uuid: aaaaaaaa-0000-0000-0000-000000000001
orchestrator: loop
context_manager: simple
provider: anthropic
services:
  - name: mock_service
    installer: pip
"""
        registry.register_definition(agent_yaml)

        resolved = asyncio.run(resolve_agent(registry, "mock-agent"))
        config = build_session_config(resolved)

        assert config.services == ["mock_service"]
        assert config.orchestrator == "loop"
        assert config.context_manager == "simple"
        assert config.provider == "anthropic"


# ---------------------------------------------------------------------------
# Integration test 2: full stack with real subprocess
# ---------------------------------------------------------------------------


class TestHostBuildRegistryFromCliDefinitions:
    @pytest.mark.timeout(30)
    def test_host_build_registry_from_cli_definitions(self, tmp_path: Path) -> None:
        """Full stack: CLI definitions produce a working Host that builds capability registry.

        Proves:
          - Registry + definition resolution produces a valid SessionConfig
          - Host can be created from that SessionConfig
          - A real mock service subprocess, injected into host._services, is
            correctly described and registered via host._build_registry()
          - The echo tool is attributed to 'mock_service' in the registry
        """
        asyncio.run(self._run(tmp_path))

    async def _run(self, tmp_path: Path) -> None:
        # ── Step 1: Set up CLI registry with agent YAML ──────────────────────
        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
type: agent
local_ref: mock-agent
uuid: bbbbbbbb-0000-0000-0000-000000000002
orchestrator: loop
context_manager: simple
provider: anthropic
services:
  - name: mock_service
    installer: pip
"""
        registry.register_definition(agent_yaml)

        # ── Step 2: Resolve definition → SessionConfig via CLI pipeline ───────
        resolved = await resolve_agent(registry, "mock-agent")
        config = build_session_config(resolved)

        assert config.services == ["mock_service"]

        # ── Step 3: Create Host from SessionConfig ────────────────────────────
        settings = HostSettings()
        host = Host(config=config, settings=settings)

        # ── Step 4: Create mock service package and spawn real subprocess ─────
        pkg_parent = _create_mock_service_package(tmp_path)
        service = await _spawn_mock(pkg_parent)

        try:
            # ── Step 5: Inject subprocess into host (bypasses _spawn_services) ─
            host._services = {"mock_service": service}

            # ── Step 6: Build capability registry from real subprocess ─────────
            await host._build_registry()

            # ── Step 7: Verify echo tool is correctly attributed ───────────────
            assert host._registry.get_tool_service("echo") == "mock_service"

        finally:
            await shutdown_service(service, timeout=5.0)
