"""Tests for session_launcher.py - bridges definition resolution and Host creation."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

from amplifier_ipc.host.config import ServiceOverride
from amplifier_ipc.host.definitions import ResolvedAgent, ServiceEntry


# ---------------------------------------------------------------------------
# Test 1: test_build_session_config_basic — uses (ref, ServiceEntry) tuples
# ---------------------------------------------------------------------------


class TestBuildSessionConfigBasic:
    def test_build_session_config_basic(self) -> None:
        """build_session_config extracts refs from (ref, ServiceEntry) tuples."""
        from amplifier_ipc.cli.session_launcher import build_session_config

        resolved = ResolvedAgent(
            services=[("test-service", ServiceEntry(stack="my-stack"))],
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
        """build_session_config maps multiple (ref, ServiceEntry) tuples to refs."""
        from amplifier_ipc.cli.session_launcher import build_session_config

        resolved = ResolvedAgent(
            services=[
                ("amplifier-foundation", ServiceEntry()),
                ("agent-browser", ServiceEntry()),
                ("amplifier-modes", ServiceEntry()),
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
        from amplifier_ipc.cli.session_launcher import build_session_config

        component_config = {
            "my-tool": {"timeout": 30, "max_retries": 3},
            "another-component": {"enabled": True},
        }

        resolved = ResolvedAgent(
            services=[("test-service", ServiceEntry())],
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
# Test 3b: test_build_service_overrides — new tuple-based API
# ---------------------------------------------------------------------------


class TestBuildServiceOverridesNewAPI:
    def test_creates_override_keyed_by_ref(self) -> None:
        """_build_service_overrides creates ServiceOverride keyed by ref when svc.command set."""
        from amplifier_ipc.cli.session_launcher import _build_service_overrides

        services = [("my-svc-ref", ServiceEntry(command="my-command"))]
        result = _build_service_overrides(services, {})

        assert "my-svc-ref" in result
        assert result["my-svc-ref"].command == ["my-command"]
        assert result["my-svc-ref"].working_dir is None

    def test_skips_service_without_command(self) -> None:
        """_build_service_overrides skips services with no command field."""
        from amplifier_ipc.cli.session_launcher import _build_service_overrides

        services = [("my-svc-ref", ServiceEntry(source="/some/path"))]
        result = _build_service_overrides(services, {})

        assert "my-svc-ref" not in result

    def test_existing_overrides_take_priority(self) -> None:
        """_build_service_overrides does not replace already-present overrides."""
        from amplifier_ipc.cli.session_launcher import _build_service_overrides

        existing = {"my-svc-ref": ServiceOverride(command=["existing-cmd"])}
        services = [("my-svc-ref", ServiceEntry(command="new-command"))]
        result = _build_service_overrides(services, existing)

        assert result["my-svc-ref"].command == ["existing-cmd"]

    def test_merges_new_overrides_with_existing(self) -> None:
        """_build_service_overrides preserves existing overrides and adds new ones."""
        from amplifier_ipc.cli.session_launcher import _build_service_overrides

        existing = {"already-there": ServiceOverride(command=["old-cmd"])}
        services = [("new-svc", ServiceEntry(command="new-cmd"))]
        result = _build_service_overrides(services, existing)

        assert "already-there" in result
        assert result["already-there"].command == ["old-cmd"]
        assert "new-svc" in result
        assert result["new-svc"].command == ["new-cmd"]

    def test_multiple_services_mixed(self) -> None:
        """_build_service_overrides handles mix of command/no-command services."""
        from amplifier_ipc.cli.session_launcher import _build_service_overrides

        services = [
            ("svc-with-cmd", ServiceEntry(command="run-me")),
            ("svc-no-cmd", ServiceEntry(stack="some-stack")),
        ]
        result = _build_service_overrides(services, {})

        assert "svc-with-cmd" in result
        assert result["svc-with-cmd"].command == ["run-me"]
        assert "svc-no-cmd" not in result


# ---------------------------------------------------------------------------
# Test 4: test_launch_session_creates_host
# ---------------------------------------------------------------------------


class TestLaunchSessionCreatesHost:
    def test_launch_session_creates_host(self, tmp_path: Path) -> None:
        """launch_session creates and returns a Host with the correct SessionConfig.

        The SessionConfig.services list contains the agent ref (from the resolved
        (ref, ServiceEntry) tuple), not a separate service name field.
        """
        from amplifier_ipc.host.definition_registry import Registry
        from amplifier_ipc.cli.session_launcher import launch_session

        # Set up a real registry with a minimal agent definition
        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
agent:
  ref: test-agent
  uuid: aaaaaaaa-0000-0000-0000-000000000001
  orchestrator: streaming
  context_manager: simple
  provider: anthropic
  service:
    stack: my-stack
"""
        registry.register_definition(agent_yaml)

        # Mock the Host class so we can capture construction args without spawning
        mock_host_instance = MagicMock()

        with patch("amplifier_ipc.cli.session_launcher.Host") as mock_host_class:
            mock_host_class.return_value = mock_host_instance

            result = asyncio.run(launch_session("test-agent", registry=registry))

        # Host should have been instantiated once
        assert mock_host_class.call_count == 1

        # Extract the SessionConfig passed to Host()
        call_args = mock_host_class.call_args
        session_config = call_args[0][0]  # first positional arg

        # The service list contains the agent ref (keyed by ref in ResolvedAgent.services)
        assert session_config.services == ["test-agent"]
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
        from amplifier_ipc.host.definition_registry import Registry
        from amplifier_ipc.cli.session_launcher import launch_session

        # Set up a real registry with a minimal agent definition
        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
agent:
  ref: test-agent
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

        with patch("amplifier_ipc.cli.session_launcher.Host") as mock_host_class:
            mock_host_class.return_value = mock_host_instance

            _ = asyncio.run(
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


class TestLaunchSessionBuildsCommandOverride:
    def test_launch_session_builds_override_for_command_services(
        self, tmp_path: Path
    ) -> None:
        """launch_session builds ServiceOverride from service command field.

        Services with a command: field in their definition should automatically
        get a ServiceOverride with that command so that the Host can spawn them
        without any hardcoded settings.yaml entries.
        """
        from amplifier_ipc.host.definition_registry import Registry
        from amplifier_ipc.cli.session_launcher import launch_session

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
agent:
  ref: cmd-agent
  uuid: aaaaaaaa-0000-0000-0000-000000000010
  orchestrator: streaming
  context_manager: simple
  provider: anthropic
  service:
    command: my-service-command
"""
        registry.register_definition(agent_yaml)

        mock_host_instance = MagicMock()

        with patch("amplifier_ipc.cli.session_launcher.Host") as mock_host_class:
            mock_host_class.return_value = mock_host_instance

            asyncio.run(launch_session("cmd-agent", registry=registry))

        assert mock_host_class.call_count == 1
        call_args = mock_host_class.call_args
        host_settings = call_args[0][1]  # second positional arg

        # A ServiceOverride keyed by agent ref should have been built
        assert "cmd-agent" in host_settings.service_overrides
        override = host_settings.service_overrides["cmd-agent"]
        assert override.command == ["my-service-command"]
        assert override.working_dir is None

    def test_launch_session_settings_override_takes_priority_over_command(
        self, tmp_path: Path
    ) -> None:
        """Settings file overrides take priority over service command auto-discovery."""
        from amplifier_ipc.host.definition_registry import Registry
        from amplifier_ipc.cli.session_launcher import launch_session

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
agent:
  ref: priority-agent
  uuid: aaaaaaaa-0000-0000-0000-000000000011
  orchestrator: streaming
  context_manager: simple
  provider: anthropic
  service:
    command: auto-discovered-command
"""
        registry.register_definition(agent_yaml)

        # Settings file overrides this service ref with a custom command
        project_settings_dir = tmp_path / ".amplifier"
        project_settings_dir.mkdir()
        project_settings_path = project_settings_dir / "settings.yaml"
        project_settings_path.write_text(
            "amplifier_ipc:\n"
            "  service_overrides:\n"
            "    priority-agent:\n"
            "      command: [custom-command]\n"
        )

        mock_host_instance = MagicMock()

        with patch("amplifier_ipc.cli.session_launcher.Host") as mock_host_class:
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

        # Settings override should win — not the service command auto-discovery
        override = host_settings.service_overrides["priority-agent"]
        assert override.command == ["custom-command"]


# ---------------------------------------------------------------------------
# Test 7: service_configs wiring — critical integration fix
# ---------------------------------------------------------------------------


class TestLaunchSessionPassesServiceConfigs:
    def test_launch_session_passes_service_configs_to_host(
        self, tmp_path: Path
    ) -> None:
        """launch_session must wire resolved.service_configs to the Host constructor.

        service_configs is computed by resolve_agent() and contains per-service
        merged component configuration needed by the configure protocol.
        If not passed to Host, configure is never sent in production.
        """
        from amplifier_ipc.host.definition_registry import Registry
        from amplifier_ipc.cli.session_launcher import launch_session

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        # Agent with component_config — resolve_agent will produce non-empty service_configs
        agent_yaml = """\
agent:
  ref: config-agent
  uuid: aaaaaaaa-0000-0000-0000-000000000099
  service:
    stack: my-stack
  component_config:
    my-tool:
      model: claude-3-sonnet
"""
        registry.register_definition(agent_yaml)

        mock_host_instance = MagicMock()

        with patch("amplifier_ipc.cli.session_launcher.Host") as mock_host_class:
            mock_host_class.return_value = mock_host_instance
            asyncio.run(launch_session("config-agent", registry=registry))

        call_args = mock_host_class.call_args
        # Host must be called with service_configs keyword argument
        assert call_args is not None
        host_kwargs = call_args.kwargs if call_args.kwargs else {}

        # service_configs should be passed as a keyword argument
        assert "service_configs" in host_kwargs, (
            "launch_session must pass service_configs= to Host() "
            "so the configure protocol fires in production"
        )
        # The service_configs should contain the agent's component_config
        service_configs = host_kwargs["service_configs"]
        assert isinstance(service_configs, dict)
        # The agent ref "config-agent" should map to its component_config
        assert "config-agent" in service_configs
        assert service_configs["config-agent"].get("my-tool") == {
            "model": "claude-3-sonnet"
        }

    def test_host_service_configs_constructor_accepts_kwarg(self) -> None:
        """Host.__init__ must accept service_configs as a keyword argument."""
        from amplifier_ipc.host.host import Host
        from amplifier_ipc.host.config import HostSettings, SessionConfig

        config = SessionConfig(
            services=[], orchestrator="", context_manager="", provider=""
        )
        settings = HostSettings()
        service_configs = {"my-svc": {"tool-a": {"key": "value"}}}

        # This must not raise TypeError
        host = Host(config, settings, service_configs=service_configs)
        assert host._service_configs == service_configs
