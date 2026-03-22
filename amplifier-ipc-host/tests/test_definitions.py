"""Tests for the definitions module (moved from amplifier-ipc-cli)."""

from __future__ import annotations

import pytest

from amplifier_ipc_host.definitions import (
    AgentDefinition,
    BehaviorDefinition,
    ResolvedAgent,
    parse_agent_definition,
    parse_behavior_definition,
    resolve_agent,
)
from amplifier_ipc_host.definition_registry import Registry


def test_parse_agent_definition_basic() -> None:
    """parse_agent_definition() correctly parses a minimal agent YAML."""
    yaml_content = """\
type: agent
local_ref: my-agent
uuid: 12345678-abcd-ef00-0000-000000000000
version: 1
description: A test agent
orchestrator: default
provider: anthropic
behaviors:
  - some-behavior
services:
  - name: my-service
    installer: pip
"""

    result = parse_agent_definition(yaml_content)

    assert isinstance(result, AgentDefinition)
    assert result.type == "agent"
    assert result.local_ref == "my-agent"
    assert result.uuid == "12345678-abcd-ef00-0000-000000000000"
    assert result.version == "1"
    assert result.description == "A test agent"
    assert result.orchestrator == "default"
    assert result.provider == "anthropic"
    assert result.behaviors == ["some-behavior"]
    assert len(result.services) == 1
    assert result.services[0].name == "my-service"
    assert result.services[0].installer == "pip"


def test_parse_behavior_definition_basic() -> None:
    """parse_behavior_definition() correctly parses a minimal behavior YAML."""
    yaml_content = """\
type: behavior
local_ref: my-behavior
uuid: abcdefab-0000-0000-0000-000000000000
version: 2
description: A test behavior
services:
  - name: behavior-service
    source: https://example.com/service
tools:
  - bash
  - read_file
"""

    result = parse_behavior_definition(yaml_content)

    assert isinstance(result, BehaviorDefinition)
    assert result.type == "behavior"
    assert result.local_ref == "my-behavior"
    assert result.uuid == "abcdefab-0000-0000-0000-000000000000"
    assert result.version == "2"
    assert result.description == "A test behavior"
    assert len(result.services) == 1
    assert result.services[0].name == "behavior-service"
    assert result.services[0].source == "https://example.com/service"
    assert result.tools == ["bash", "read_file"]


async def test_resolve_agent_deduplicates_services(tmp_path) -> None:
    """resolve_agent() deduplicates services by name across agent and behavior definitions."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    # Register a behavior with a service
    behavior_yaml = """\
type: behavior
local_ref: my-behavior
uuid: bbbbbbbb-0000-0000-0000-000000000000
services:
  - name: shared-service
    installer: pip
  - name: behavior-only-service
"""
    registry.register_definition(behavior_yaml)

    # Register an agent that also declares the same shared-service
    agent_yaml = """\
type: agent
local_ref: my-agent
uuid: aaaaaaaa-0000-0000-0000-000000000000
behaviors:
  - my-behavior
services:
  - name: shared-service
    installer: pip
"""
    registry.register_definition(agent_yaml)

    result = await resolve_agent(registry, "my-agent")

    assert isinstance(result, ResolvedAgent)
    # Services should be deduplicated — shared-service appears once
    service_names = [s.name for s in result.services]
    assert service_names.count("shared-service") == 1
    assert "behavior-only-service" in service_names


def test_parse_agent_definition_tools_bool_true() -> None:
    """parse_agent_definition() handles boolean shorthand (tools: true) without crashing.

    'true' means 'enable all from this service' — parsed as an empty list sentinel.
    Same for hooks, agents, and context.
    """
    yaml_content = """\
type: agent
local_ref: foundation
uuid: 3898a638-71de-427a-8183-b80eba8b26be
orchestrator: foundation:streaming
context_manager: foundation:simple
provider: providers:anthropic
tools: true
hooks: true
agents: true
context: true
"""
    result = parse_agent_definition(yaml_content)

    assert isinstance(result.tools, list)
    assert isinstance(result.hooks, list)
    assert isinstance(result.agents, list)
    assert isinstance(result.context, dict)


def test_parse_agent_definition_tools_bool_false() -> None:
    """parse_agent_definition() handles 'false' booleans — treated as empty list/dict."""
    yaml_content = """\
type: agent
local_ref: my-agent
uuid: 12345678-abcd-ef00-0000-000000000000
tools: false
hooks: false
"""
    result = parse_agent_definition(yaml_content)
    assert result.tools == []
    assert result.hooks == []


def test_parse_behavior_definition_tools_bool_true() -> None:
    """parse_behavior_definition() handles boolean shorthand (tools: true) without crashing."""
    yaml_content = """\
type: behavior
local_ref: my-behavior
uuid: bbbbbbbb-0000-0000-0000-000000000000
tools: true
hooks: true
context: true
"""
    result = parse_behavior_definition(yaml_content)

    assert isinstance(result.tools, list)
    assert isinstance(result.hooks, list)
    assert isinstance(result.context, dict)


async def test_resolve_agent_unknown_raises(tmp_path) -> None:
    """resolve_agent() raises FileNotFoundError for an unregistered agent."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    with pytest.raises(FileNotFoundError, match="nonexistent-agent"):
        await resolve_agent(registry, "nonexistent-agent")


def test_relative_source_resolved_against_definition_dir(tmp_path) -> None:
    """parse_agent_definition() resolves relative source paths against the definition file's dir.

    Creates a tmp_path structure with definitions/ and services/ dirs,
    parses YAML with relative source '../services/my-service', and verifies
    the resolved path is absolute and points to the correct directory.
    """
    from pathlib import Path

    # Set up directory structure
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    service_dir = tmp_path / "services" / "my-service"
    service_dir.mkdir(parents=True)

    # Write the definition YAML file with a relative source path
    yaml_content = """\
type: agent
local_ref: my-agent
uuid: 12345678-abcd-ef00-0000-000000000000
services:
  - name: my-service
    source: ../services/my-service
"""
    definition_path = definitions_dir / "my-agent.yaml"
    definition_path.write_text(yaml_content)

    # Parse with path so relative sources are resolved
    result = parse_agent_definition(yaml_content, path=definition_path)

    assert len(result.services) == 1
    svc = result.services[0]
    assert svc.source is not None
    resolved = Path(svc.source)
    assert resolved.is_absolute(), f"Expected absolute path, got: {svc.source}"
    assert resolved == service_dir.resolve(), (
        f"Expected {service_dir.resolve()}, got {resolved}"
    )
