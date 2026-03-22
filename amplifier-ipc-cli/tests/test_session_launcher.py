"""Tests for session_launcher.py - bridges definition resolution and Host creation."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

from amplifier_ipc_cli.definitions import ResolvedAgent, ServiceEntry


# ---------------------------------------------------------------------------
# Test 1: test_build_session_config_basic
# ---------------------------------------------------------------------------


class TestBuildSessionConfigBasic:
    def test_build_session_config_basic(self) -> None:
        """build_session_config maps services/orchestrator/context_manager/provider."""
        from amplifier_ipc_cli.session_launcher import build_session_config

        resolved = ResolvedAgent(
            services=[ServiceEntry(name="test-service")],
            orchestrator="streaming",
            context_manager="simple",
            provider="anthropic",
            component_config={},
        )

        config = build_session_config(resolved)

        assert config.services == ["test-service"]
        assert config.orchestrator == "streaming"
        assert config.context_manager == "simple"
        assert config.provider == "anthropic"


# ---------------------------------------------------------------------------
# Test 2: test_build_session_config_multiple_services
# ---------------------------------------------------------------------------


class TestBuildSessionConfigMultipleServices:
    def test_build_session_config_multiple_services(self) -> None:
        """build_session_config maps multiple services to a list of service names."""
        from amplifier_ipc_cli.session_launcher import build_session_config

        resolved = ResolvedAgent(
            services=[
                ServiceEntry(name="amplifier-foundation"),
                ServiceEntry(name="agent-browser"),
                ServiceEntry(name="amplifier-modes"),
            ],
            orchestrator="streaming",
            context_manager="simple",
            provider="anthropic",
            component_config={},
        )

        config = build_session_config(resolved)

        assert config.services == [
            "amplifier-foundation",
            "agent-browser",
            "amplifier-modes",
        ]
        assert len(config.services) == 3


# ---------------------------------------------------------------------------
# Test 3: test_build_session_config_preserves_component_config
# ---------------------------------------------------------------------------


class TestBuildSessionConfigPreservesComponentConfig:
    def test_build_session_config_preserves_component_config(self) -> None:
        """build_session_config passes component_config through unchanged."""
        from amplifier_ipc_cli.session_launcher import build_session_config

        component_config = {
            "my-tool": {"timeout": 30, "max_retries": 3},
            "another-component": {"enabled": True},
        }

        resolved = ResolvedAgent(
            services=[ServiceEntry(name="test-service")],
            orchestrator="streaming",
            context_manager="simple",
            provider="anthropic",
            component_config=component_config,
        )

        config = build_session_config(resolved)

        assert config.component_config == component_config
        assert config.component_config["my-tool"]["timeout"] == 30
        assert config.component_config["another-component"]["enabled"] is True


# ---------------------------------------------------------------------------
# Test 4: test_launch_session_creates_host
# ---------------------------------------------------------------------------


class TestLaunchSessionCreatesHost:
    def test_launch_session_creates_host(self, tmp_path: Path) -> None:
        """launch_session creates and returns a Host with the correct SessionConfig."""
        from amplifier_ipc_cli.registry import Registry
        from amplifier_ipc_cli.session_launcher import launch_session

        # Set up a real registry with a minimal agent definition
        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
type: agent
local_ref: test-agent
uuid: aaaaaaaa-0000-0000-0000-000000000001
orchestrator: streaming
context_manager: simple
provider: anthropic
services:
  - name: test-service
    installer: pip
"""
        registry.register_definition(agent_yaml)

        # Mock the Host class so we can capture construction args without spawning
        mock_host_instance = MagicMock()

        with patch("amplifier_ipc_cli.session_launcher.Host") as mock_host_class:
            mock_host_class.return_value = mock_host_instance

            result = asyncio.run(launch_session("test-agent", registry=registry))

        # Host should have been instantiated once
        assert mock_host_class.call_count == 1

        # Extract the SessionConfig passed to Host()
        call_args = mock_host_class.call_args
        session_config = call_args[0][0]  # first positional arg

        # Verify SessionConfig was built correctly
        assert session_config.services == ["test-service"]
        assert session_config.orchestrator == "streaming"

        # launch_session should return the Host instance
        assert result is mock_host_instance


# ---------------------------------------------------------------------------
# Test 5: test_launch_session_loads_settings_from_files
# ---------------------------------------------------------------------------


class TestLaunchSessionLoadsSettings:
    def test_launch_session_loads_settings_from_project_file(
        self, tmp_path: Path
    ) -> None:
        """launch_session passes HostSettings loaded from the project settings file.

        When a project-level settings file contains service_overrides, those
        overrides must be present in the HostSettings passed to the Host so that
        resolve_service_command() can find custom commands.
        """
        from amplifier_ipc_cli.registry import Registry
        from amplifier_ipc_cli.session_launcher import launch_session

        # Set up a real registry with a minimal agent definition
        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
type: agent
local_ref: test-agent
uuid: aaaaaaaa-0000-0000-0000-000000000002
orchestrator: streaming
context_manager: simple
provider: anthropic
services:
  - name: my-service
"""
        registry.register_definition(agent_yaml)

        # Create a project settings file with a service override
        project_settings_dir = tmp_path / ".amplifier"
        project_settings_dir.mkdir()
        project_settings_path = project_settings_dir / "settings.yaml"
        project_settings_path.write_text(
            "amplifier_ipc:\n"
            "  service_overrides:\n"
            "    my-service:\n"
            "      command: [python, -m, my_service]\n"
            "      working_dir: /tmp/my-service\n"
        )

        mock_host_instance = MagicMock()

        with patch("amplifier_ipc_cli.session_launcher.Host") as mock_host_class:
            mock_host_class.return_value = mock_host_instance

            result = asyncio.run(
                launch_session(
                    "test-agent",
                    registry=registry,
                    project_settings_path=project_settings_path,
                )
            )

        assert mock_host_class.call_count == 1
        call_args = mock_host_class.call_args
        host_settings = call_args[0][1]  # second positional arg

        # The override should have been loaded
        assert "my-service" in host_settings.service_overrides
        override = host_settings.service_overrides["my-service"]
        assert override.command == ["python", "-m", "my_service"]
        assert override.working_dir == "/tmp/my-service"


# ---------------------------------------------------------------------------
# Test 6: test_launch_session_builds_uv_run_override_for_source_services
# ---------------------------------------------------------------------------


class TestLaunchSessionBuildsUvRunOverride:
    def test_launch_session_builds_uv_run_override_for_source_services(
        self, tmp_path: Path
    ) -> None:
        """launch_session builds 'uv run --directory <source>' overrides for source services.

        Services with a source: path in their definition should automatically
        get a ServiceOverride using 'uv run --directory <source> <name>' so
        that the Host can spawn them without any hardcoded settings.yaml entries.
        """
        from amplifier_ipc_cli.registry import Registry
        from amplifier_ipc_cli.session_launcher import launch_session

        source_path = str(tmp_path / "my-service-src")

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = f"""\
type: agent
local_ref: source-agent
uuid: aaaaaaaa-0000-0000-0000-000000000010
orchestrator: streaming
context_manager: simple
provider: anthropic
services:
  - name: my-source-service
    source: {source_path}
"""
        registry.register_definition(agent_yaml)

        mock_host_instance = MagicMock()

        with patch("amplifier_ipc_cli.session_launcher.Host") as mock_host_class:
            mock_host_class.return_value = mock_host_instance

            asyncio.run(launch_session("source-agent", registry=registry))

        assert mock_host_class.call_count == 1
        call_args = mock_host_class.call_args
        host_settings = call_args[0][1]  # second positional arg

        # A uv run override should have been built for the source service
        assert "my-source-service" in host_settings.service_overrides
        override = host_settings.service_overrides["my-source-service"]
        assert override.command == [
            "uv",
            "run",
            "--directory",
            source_path,
            "my-source-service",
        ]
        assert override.working_dir == source_path

    def test_launch_session_settings_override_takes_priority_over_source(
        self, tmp_path: Path
    ) -> None:
        """Settings file overrides take priority over source-path auto-discovery."""
        from amplifier_ipc_cli.registry import Registry
        from amplifier_ipc_cli.session_launcher import launch_session

        source_path = str(tmp_path / "my-service-src")

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = f"""\
type: agent
local_ref: priority-agent
uuid: aaaaaaaa-0000-0000-0000-000000000011
orchestrator: streaming
context_manager: simple
provider: anthropic
services:
  - name: my-service
    source: {source_path}
"""
        registry.register_definition(agent_yaml)

        # Settings file overrides this service with a custom command
        project_settings_dir = tmp_path / ".amplifier"
        project_settings_dir.mkdir()
        project_settings_path = project_settings_dir / "settings.yaml"
        project_settings_path.write_text(
            "amplifier_ipc:\n"
            "  service_overrides:\n"
            "    my-service:\n"
            "      command: [custom-command]\n"
        )

        mock_host_instance = MagicMock()

        with patch("amplifier_ipc_cli.session_launcher.Host") as mock_host_class:
            mock_host_class.return_value = mock_host_instance

            asyncio.run(
                launch_session(
                    "priority-agent",
                    registry=registry,
                    project_settings_path=project_settings_path,
                )
            )

        call_args = mock_host_class.call_args
        host_settings = call_args[0][1]

        # Settings override should win — not the uv run auto-discovery
        override = host_settings.service_overrides["my-service"]
        assert override.command == ["custom-command"]
