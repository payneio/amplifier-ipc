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
