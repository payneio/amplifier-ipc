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


def _mock_registry(installed: bool = False) -> MagicMock:
    """Create a mock Registry that reports no environments installed by default."""
    reg = MagicMock()
    reg.is_installed.return_value = installed
    reg.get_environment_path.return_value = Path("/fake/env")
    return reg


class TestBuildServiceOverridesNewAPI:
    def test_creates_override_keyed_by_ref(self) -> None:
        """_build_service_overrides creates ServiceOverride keyed by ref when svc.command set."""
        from amplifier_ipc.cli.session_launcher import _build_service_overrides

        services = [("my-svc-ref", ServiceEntry(command="my-command"))]
        result = _build_service_overrides(services, {}, _mock_registry(), {})

        assert "my-svc-ref" in result
        assert result["my-svc-ref"].command == ["my-command"]
        assert result["my-svc-ref"].working_dir is None

    def test_skips_service_without_command(self) -> None:
        """_build_service_overrides skips services with no command field."""
        from amplifier_ipc.cli.session_launcher import _build_service_overrides

        services = [("my-svc-ref", ServiceEntry(source="/some/path"))]
        result = _build_service_overrides(services, {}, _mock_registry(), {})

        assert "my-svc-ref" not in result

    def test_existing_overrides_take_priority(self) -> None:
        """_build_service_overrides does not replace already-present overrides."""
        from amplifier_ipc.cli.session_launcher import _build_service_overrides

        existing = {"my-svc-ref": ServiceOverride(command=["existing-cmd"])}
        services = [("my-svc-ref", ServiceEntry(command="new-command"))]
        result = _build_service_overrides(services, existing, _mock_registry(), {})

        assert result["my-svc-ref"].command == ["existing-cmd"]

    def test_merges_new_overrides_with_existing(self) -> None:
        """_build_service_overrides preserves existing overrides and adds new ones."""
        from amplifier_ipc.cli.session_launcher import _build_service_overrides

        existing = {"already-there": ServiceOverride(command=["old-cmd"])}
        services = [("new-svc", ServiceEntry(command="new-cmd"))]
        result = _build_service_overrides(services, existing, _mock_registry(), {})

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
        result = _build_service_overrides(services, {}, _mock_registry(), {})

        assert "svc-with-cmd" in result
        assert result["svc-with-cmd"].command == ["run-me"]
        assert "svc-no-cmd" not in result

    def test_resolves_command_to_env_bin_when_installed(self, tmp_path: Path) -> None:
        """_build_service_overrides resolves command to full env bin path when installed."""
        from amplifier_ipc.cli.session_launcher import _build_service_overrides

        # Create a fake environment with the binary
        env_path = tmp_path / "env"
        bin_dir = env_path / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "my-command").touch()

        registry = MagicMock()
        registry.is_installed.return_value = True
        registry.get_environment_path.return_value = env_path

        services = [("my-svc", ServiceEntry(command="my-command"))]
        definition_ids = {"my-svc": "agent_my-svc_abc123"}
        result = _build_service_overrides(services, {}, registry, definition_ids)

        assert result["my-svc"].command == [str(bin_dir / "my-command")]


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

        When a project-level settings file contains service_overrides in the new
        nested agent→service format, those overrides must be present in the
        HostSettings passed to the Host so that resolve_service_command() can
        find custom commands.

        New settings format (nested by agent name):
            amplifier_ipc:
              service_overrides:
                <agent_name>:
                  <service_ref>:
                    command: [...]
                    working_dir: ...
        """
        from amplifier_ipc.host.definition_registry import Registry
        from amplifier_ipc.cli.session_launcher import launch_session

        # Set up a real registry with a minimal agent definition (new format)
        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
agent:
  ref: test-agent
  uuid: aaaaaaaa-0000-0000-0000-000000000002
  orchestrator: streaming
  context_manager: simple
  provider: anthropic
  service:
    stack: uv
    command: my-service-cmd
"""
        registry.register_definition(agent_yaml)

        # Create a project settings file with a service override in nested format.
        # The service ref here matches the agent ref ("test-agent") since the agent's
        # own service is keyed by the agent ref in resolved services.
        project_settings_dir = tmp_path / ".amplifier"
        project_settings_dir.mkdir()
        project_settings_path = project_settings_dir / "settings.yaml"
        project_settings_path.write_text(
            "amplifier_ipc:\n"
            "  service_overrides:\n"
            "    test-agent:\n"  # agent name
            "      test-agent:\n"  # service ref (= agent ref for agent's own service)
            "        command: [python, -m, my_service]\n"
            "        working_dir: /tmp/my-service\n"
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

        # The override should have been loaded (service ref = agent ref = "test-agent")
        assert "test-agent" in host_settings.service_overrides
        override = host_settings.service_overrides["test-agent"]
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
        """Settings file overrides take priority over service command auto-discovery.

        Uses the new nested agent→service settings format.
        """
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

        # Settings file overrides this service ref with a custom command.
        # Uses new nested format: service_overrides.<agent_name>.<service_ref>
        project_settings_dir = tmp_path / ".amplifier"
        project_settings_dir.mkdir()
        project_settings_path = project_settings_dir / "settings.yaml"
        project_settings_path.write_text(
            "amplifier_ipc:\n"
            "  service_overrides:\n"
            "    priority-agent:\n"  # agent name
            "      priority-agent:\n"  # service ref (= agent ref for agent's own service)
            "        command: [custom-command]\n"
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


# ---------------------------------------------------------------------------
# Test 8: launch_session passes agent_name to load_settings for nested format
# ---------------------------------------------------------------------------


class TestLaunchSessionNestedSettingsFormat:
    def test_launch_session_reads_nested_agent_scoped_settings(
        self, tmp_path: Path
    ) -> None:
        """launch_session uses agent_name when loading nested settings.yaml format.

        The .amplifier/settings.yaml uses a nested structure where service overrides
        are scoped under the agent name:

            amplifier_ipc:
              service_overrides:
                my-agent:
                  my-service:
                    command: [uv, run, my-service]

        launch_session must pass agent_name= to load_settings so that the per-service
        overrides under 'my-agent' are extracted, not treated as flat service names.
        """
        from amplifier_ipc.host.definition_registry import Registry
        from amplifier_ipc.cli.session_launcher import launch_session

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        # Agent with a service that has a command
        agent_yaml = """\
agent:
  ref: nested-agent
  uuid: aaaaaaaa-0000-0000-0000-000000000020
  orchestrator: streaming
  context_manager: simple
  provider: anthropic
  service:
    stack: uv
    command: default-command
"""
        registry.register_definition(agent_yaml)

        # Settings file using NESTED format: agent -> service -> override
        project_settings_dir = tmp_path / ".amplifier"
        project_settings_dir.mkdir()
        project_settings_path = project_settings_dir / "settings.yaml"
        project_settings_path.write_text(
            "amplifier_ipc:\n"
            "  service_overrides:\n"
            "    nested-agent:\n"
            "      nested-agent:\n"  # service ref matches agent ref
            "        command: [uv, run, --directory, ./services/nested, nested-serve]\n"
            "        working_dir: ./services/nested\n"
        )

        mock_host_instance = MagicMock()

        with patch("amplifier_ipc.cli.session_launcher.Host") as mock_host_class:
            mock_host_class.return_value = mock_host_instance

            asyncio.run(
                launch_session(
                    "nested-agent",
                    registry=registry,
                    project_settings_path=project_settings_path,
                )
            )

        call_args = mock_host_class.call_args
        host_settings = call_args[0][1]

        # The settings-file override for the service (keyed by service ref = agent ref)
        # should have been extracted from the nested format
        assert "nested-agent" in host_settings.service_overrides
        override = host_settings.service_overrides["nested-agent"]
        assert override.command == [
            "uv",
            "run",
            "--directory",
            "./services/nested",
            "nested-serve",
        ]
        assert override.working_dir == "./services/nested"

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


# ---------------------------------------------------------------------------
# Test 9: Lazy install on first run
# ---------------------------------------------------------------------------


class TestLazyInstallOnFirstRun:
    def test_lazy_install_installs_uninstalled_services(self, tmp_path: Path) -> None:
        """launch_session calls install_service for services with source that aren't installed."""
        from amplifier_ipc.host.definition_registry import Registry
        from amplifier_ipc.cli.session_launcher import launch_session

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
agent:
  ref: lazy-agent
  uuid: cccccccc-0000-0000-0000-000000000001
  service:
    source: my-package>=1.0
"""
        registry.register_definition(agent_yaml)
        # Environment directory does NOT exist, so is_installed() returns False.

        mock_host_instance = MagicMock()

        with (
            patch("amplifier_ipc.cli.session_launcher.Host") as mock_host_class,
            patch("amplifier_ipc.cli.session_launcher.install_service") as mock_install,
        ):
            mock_host_class.return_value = mock_host_instance
            asyncio.run(launch_session("lazy-agent", registry=registry))

        mock_install.assert_called_once()
        call_args = mock_install.call_args
        assert call_args[0][0] is registry
        assert (
            call_args[0][1] == "agent_lazy-agent_cccccccc-0000-0000-0000-000000000001"
        )
        assert call_args[0][2] == "my-package>=1.0"

    def test_lazy_install_skips_already_installed(self, tmp_path: Path) -> None:
        """launch_session skips install_service when the environment already exists."""
        from amplifier_ipc.host.definition_registry import Registry
        from amplifier_ipc.cli.session_launcher import launch_session

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
agent:
  ref: installed-agent
  uuid: cccccccc-0000-0000-0000-000000000002
  service:
    source: my-package>=1.0
"""
        registry.register_definition(agent_yaml)
        definition_id = "agent_installed-agent_cccccccc-0000-0000-0000-000000000002"
        # Simulate already installed by creating the environment directory.
        (tmp_path / "amplifier_home" / "environments" / definition_id).mkdir(
            parents=True
        )

        mock_host_instance = MagicMock()

        with (
            patch("amplifier_ipc.cli.session_launcher.Host") as mock_host_class,
            patch("amplifier_ipc.cli.session_launcher.install_service") as mock_install,
        ):
            mock_host_class.return_value = mock_host_instance
            asyncio.run(launch_session("installed-agent", registry=registry))

        mock_install.assert_not_called()

    def test_lazy_install_skips_services_without_source(self, tmp_path: Path) -> None:
        """launch_session skips install_service for services that have no source field."""
        from amplifier_ipc.host.definition_registry import Registry
        from amplifier_ipc.cli.session_launcher import launch_session

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
agent:
  ref: no-source-agent
  uuid: cccccccc-0000-0000-0000-000000000003
  service:
    command: my-command
"""
        registry.register_definition(agent_yaml)
        # No 'source' field — install should be skipped even though env doesn't exist.

        mock_host_instance = MagicMock()

        with (
            patch("amplifier_ipc.cli.session_launcher.Host") as mock_host_class,
            patch("amplifier_ipc.cli.session_launcher.install_service") as mock_install,
        ):
            mock_host_class.return_value = mock_host_instance
            asyncio.run(launch_session("no-source-agent", registry=registry))

        mock_install.assert_not_called()


# ---------------------------------------------------------------------------
# Test 10: TestLaunchSessionForwardsWorkingDir
# ---------------------------------------------------------------------------


class TestLaunchSessionForwardsWorkingDir:
    def test_launch_session_forwards_working_dir_to_host(self, tmp_path: Path) -> None:
        """launch_session forwards working_dir to the Host constructor."""
        from amplifier_ipc.host.definition_registry import Registry
        from amplifier_ipc.cli.session_launcher import launch_session

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
agent:
  ref: wd-agent
  uuid: aaaaaaaa-0000-0000-0000-000000000042
  orchestrator: streaming
  context_manager: simple
  provider: anthropic
  service:
    stack: my-stack
"""
        registry.register_definition(agent_yaml)

        fake_working_dir = tmp_path / "my-working-dir"
        mock_host_instance = MagicMock()

        with patch("amplifier_ipc.cli.session_launcher.Host") as mock_host_class:
            mock_host_class.return_value = mock_host_instance
            asyncio.run(
                launch_session(
                    "wd-agent", registry=registry, working_dir=fake_working_dir
                )
            )

        assert mock_host_class.call_count == 1
        call_args = mock_host_class.call_args
        host_kwargs = call_args.kwargs if call_args.kwargs else {}
        assert host_kwargs.get("working_dir") == fake_working_dir

    def test_launch_session_omits_working_dir_when_none(self, tmp_path: Path) -> None:
        """launch_session passes working_dir=None to Host when not provided."""
        from amplifier_ipc.host.definition_registry import Registry
        from amplifier_ipc.cli.session_launcher import launch_session

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
agent:
  ref: no-wd-agent
  uuid: aaaaaaaa-0000-0000-0000-000000000043
  orchestrator: streaming
  context_manager: simple
  provider: anthropic
  service:
    stack: my-stack
"""
        registry.register_definition(agent_yaml)

        mock_host_instance = MagicMock()

        with patch("amplifier_ipc.cli.session_launcher.Host") as mock_host_class:
            mock_host_class.return_value = mock_host_instance
            asyncio.run(launch_session("no-wd-agent", registry=registry))

        assert mock_host_class.call_count == 1
        call_args = mock_host_class.call_args
        host_kwargs = call_args.kwargs if call_args.kwargs else {}
        assert host_kwargs.get("working_dir") is None


# ---------------------------------------------------------------------------
# AsyncIteratorMock helper
# ---------------------------------------------------------------------------


class AsyncIteratorMock:
    """Async iterator helper for testing async for loops over host.run() output."""

    def __init__(self, items: list) -> None:
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


# ---------------------------------------------------------------------------
# Test 11: TestRunCommandPassesWorkingDir
# ---------------------------------------------------------------------------


class TestRunCommandPassesWorkingDir:
    def test_run_agent_passes_working_dir_to_launch_session(self) -> None:
        """_run_agent converts working_dir str to Path and passes it to launch_session.

        Case 1: explicit working_dir='/tmp/my-project' -> Path('/tmp/my-project')
        Case 2: working_dir=None -> Path.cwd()
        """
        from unittest.mock import AsyncMock, patch

        from amplifier_ipc.cli.commands.run import _run_agent

        mock_host = MagicMock()
        mock_host.run.return_value = AsyncIteratorMock([])
        mock_host.session_id = None

        with (
            patch(
                "amplifier_ipc.cli.commands.run._resolve_agent_name",
                return_value="test-agent",
            ),
            patch(
                "amplifier_ipc.cli.commands.run.launch_session",
                new_callable=AsyncMock,
            ) as mock_launch,
            patch("amplifier_ipc.cli.commands.run.KeyManager") as mock_km,
        ):
            mock_launch.return_value = mock_host
            mock_km.return_value.load_keys = MagicMock()

            # Case 1: explicit working_dir string -> converted to Path
            asyncio.run(
                _run_agent(
                    "test-agent",       # agent_name_arg
                    "hello",            # message
                    [],                 # behaviors
                    None,               # session
                    None,               # project
                    "/tmp/my-project",  # working_dir
                    None,               # provider
                    None,               # model
                    None,               # max_tokens
                    False,              # verbose
                    "text",             # output_format
                )
            )

            call_kwargs = mock_launch.call_args.kwargs
            assert call_kwargs["working_dir"] == Path("/tmp/my-project")

            # Case 2: working_dir=None -> defaults to Path.cwd()
            mock_launch.reset_mock()
            mock_host.run.return_value = AsyncIteratorMock([])

            asyncio.run(
                _run_agent(
                    "test-agent",  # agent_name_arg
                    "hello",       # message
                    [],            # behaviors
                    None,          # session
                    None,          # project
                    None,          # working_dir
                    None,          # provider
                    None,          # model
                    None,          # max_tokens
                    False,         # verbose
                    "text",        # output_format
                )
            )

            call_kwargs = mock_launch.call_args.kwargs
            assert call_kwargs["working_dir"] == Path.cwd()
