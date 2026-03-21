"""Tests for session_spawner.py — thin session spawner for agent delegation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

from amplifier_ipc_host.config import SessionConfig


# ---------------------------------------------------------------------------
# Test 1: test_generate_sub_session_id_format
# ---------------------------------------------------------------------------


class TestGenerateSubSessionIdFormat:
    def test_generate_sub_session_id_format(self) -> None:
        """Generated ID contains parent_id, safe agent name parts, and 3+ parts."""
        from amplifier_ipc_cli.session_spawner import generate_sub_session_id

        parent_id = "parent123"
        agent_name = "foundation:explorer"

        result = generate_sub_session_id(parent_id, agent_name)

        # Must contain the parent session id
        assert parent_id in result

        # Must contain parts of the agent name (colons replaced with underscores)
        assert "foundation" in result
        assert "explorer" in result

        # Must have at least 3 underscore-separated parts
        parts = result.split("_")
        assert len(parts) >= 3


# ---------------------------------------------------------------------------
# Test 2: test_generate_sub_session_id_uniqueness
# ---------------------------------------------------------------------------


class TestGenerateSubSessionIdUniqueness:
    def test_generate_sub_session_id_uniqueness(self) -> None:
        """Two calls to generate_sub_session_id with same args produce different IDs."""
        from amplifier_ipc_cli.session_spawner import generate_sub_session_id

        id1 = generate_sub_session_id("parent123", "some-agent")
        id2 = generate_sub_session_id("parent123", "some-agent")

        assert id1 != id2


# ---------------------------------------------------------------------------
# Test 3: test_merge_child_config_inherits_parent_services
# ---------------------------------------------------------------------------


class TestMergeChildConfigInheritsParentServices:
    def test_merge_child_config_inherits_parent_services(self) -> None:
        """merge_child_config includes all parent services in the result."""
        from amplifier_ipc_cli.session_spawner import merge_child_config

        parent = SessionConfig(
            services=["amplifier-foundation", "amplifier-modes"],
            orchestrator="streaming",
            context_manager="simple",
            provider="anthropic",
        )

        result = merge_child_config(parent, child_services=[])

        assert "amplifier-foundation" in result.services
        assert "amplifier-modes" in result.services


# ---------------------------------------------------------------------------
# Test 4: test_merge_child_config_adds_child_services
# ---------------------------------------------------------------------------


class TestMergeChildConfigAddsChildServices:
    def test_merge_child_config_adds_child_services(self) -> None:
        """merge_child_config adds child services and deduplicates."""
        from amplifier_ipc_cli.session_spawner import merge_child_config

        parent = SessionConfig(
            services=["amplifier-foundation"],
            orchestrator="streaming",
            context_manager="simple",
            provider="anthropic",
        )

        # Add a new service and one that's already in parent (duplicate)
        result = merge_child_config(
            parent,
            child_services=["amplifier-foundation", "agent-browser"],
        )

        # Should contain both services exactly once
        assert "amplifier-foundation" in result.services
        assert "agent-browser" in result.services
        assert result.services.count("amplifier-foundation") == 1


# ---------------------------------------------------------------------------
# Test 5: test_merge_child_config_overrides_orchestrator
# ---------------------------------------------------------------------------


class TestMergeChildConfigOverridesOrchestrator:
    def test_merge_child_config_overrides_orchestrator(self) -> None:
        """merge_child_config uses child orchestrator override when provided."""
        from amplifier_ipc_cli.session_spawner import merge_child_config

        parent = SessionConfig(
            services=["amplifier-foundation"],
            orchestrator="streaming",
            context_manager="simple",
            provider="anthropic",
        )

        result = merge_child_config(
            parent,
            child_services=[],
            orchestrator="custom-orchestrator",
        )

        assert result.orchestrator == "custom-orchestrator"
        # Other fields fall back to parent
        assert result.context_manager == "simple"
        assert result.provider == "anthropic"


# ---------------------------------------------------------------------------
# Test 6: test_spawn_sub_session_creates_host
# ---------------------------------------------------------------------------


class TestSpawnSubSessionCreatesHost:
    def test_spawn_sub_session_creates_host(self, tmp_path: Path) -> None:
        """spawn_sub_session creates a Host, runs it, and returns the response string."""
        from amplifier_ipc_cli.registry import Registry
        from amplifier_ipc_cli.session_spawner import SpawnRequest, spawn_sub_session

        # Set up a minimal registry with an agent definition
        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
type: agent
local_ref: test-child-agent
uuid: bbbbbbbb-0000-0000-0000-000000000001
orchestrator: streaming
context_manager: simple
provider: anthropic
services:
  - name: child-service
    installer: pip
"""
        registry.register_definition(agent_yaml)

        parent_config = SessionConfig(
            services=["parent-service"],
            orchestrator="streaming",
            context_manager="simple",
            provider="anthropic",
        )

        request = SpawnRequest(
            agent_name="test-child-agent",
            instruction="Do something useful",
            parent_session_id="parent_abc123",
        )

        # Mock the Host class so it doesn't actually spawn subprocesses
        mock_host_instance = MagicMock()
        expected_response = "Child agent response"

        from amplifier_ipc_host.events import CompleteEvent

        async def fake_run(prompt: str):
            yield CompleteEvent(result=expected_response)

        mock_host_instance.run = fake_run

        with patch("amplifier_ipc_cli.session_spawner.Host") as mock_host_class:
            mock_host_class.return_value = mock_host_instance

            response = asyncio.run(
                spawn_sub_session(
                    request=request,
                    parent_config=parent_config,
                    registry=registry,
                )
            )

        # Host was created
        assert mock_host_class.call_count == 1

        # Response is the text from the CompleteEvent
        assert response == expected_response
