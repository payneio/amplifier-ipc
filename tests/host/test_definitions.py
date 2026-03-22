"""Tests for the definitions module (moved from amplifier-ipc-cli)."""

from __future__ import annotations

import pytest

from amplifier_ipc.host.definitions import (
    AgentDefinition,
    BehaviorDefinition,
    ResolvedAgent,
    ServiceEntry,
    _to_behavior_list,
    _to_bool,
    parse_agent_definition,
    parse_behavior_definition,
    resolve_agent,
)
from amplifier_ipc.host.definition_registry import Registry


# ---------------------------------------------------------------------------
# ServiceEntry dataclass tests
# ---------------------------------------------------------------------------


def test_service_entry_has_stack_and_command_fields() -> None:
    """ServiceEntry has stack, source, command fields (all optional str), not name/installer."""
    svc = ServiceEntry(
        stack="uv", source="git+https://example.com/pkg", command="my-serve"
    )

    assert svc.stack == "uv"
    assert svc.source == "git+https://example.com/pkg"
    assert svc.command == "my-serve"

    assert not hasattr(svc, "name"), "ServiceEntry should not have a 'name' attribute"
    assert not hasattr(svc, "installer"), (
        "ServiceEntry should not have an 'installer' attribute"
    )


# ---------------------------------------------------------------------------
# _to_bool unit tests
# ---------------------------------------------------------------------------


def test_to_bool_none() -> None:
    """_to_bool(None) returns False."""
    assert _to_bool(None) is False


def test_to_bool_true() -> None:
    """_to_bool(True) returns True."""
    assert _to_bool(True) is True


def test_to_bool_false() -> None:
    """_to_bool(False) returns False."""
    assert _to_bool(False) is False


def test_to_bool_nonempty_list() -> None:
    """_to_bool(['a', 'b']) returns True (non-empty list is truthy)."""
    assert _to_bool(["a", "b"]) is True


def test_to_bool_empty_list() -> None:
    """_to_bool([]) returns False (empty list is falsy)."""
    assert _to_bool([]) is False


# ---------------------------------------------------------------------------
# _to_behavior_list unit tests
# ---------------------------------------------------------------------------


def test_to_behavior_list_none() -> None:
    """_to_behavior_list(None) returns an empty list."""
    assert _to_behavior_list(None) == []


def test_to_behavior_list_true() -> None:
    """_to_behavior_list(True) returns an empty list."""
    assert _to_behavior_list(True) == []


def test_to_behavior_list_false() -> None:
    """_to_behavior_list(False) returns an empty list."""
    assert _to_behavior_list(False) == []


def test_to_behavior_list_flat_string_list() -> None:
    """_to_behavior_list(['a', 'b']) wraps each string as {'ref': value}."""
    assert _to_behavior_list(["a", "b"]) == [{"ref": "a"}, {"ref": "b"}]


def test_to_behavior_list_list_of_single_key_dicts() -> None:
    """_to_behavior_list([{'modes': 'url1'}, {'skills': 'url2'}]) preserves alias+url dicts."""
    result = _to_behavior_list([{"modes": "url1"}, {"skills": "url2"}])
    assert result == [{"modes": "url1"}, {"skills": "url2"}]


def test_to_behavior_list_plain_dict() -> None:
    """_to_behavior_list({'modes': 'url1', 'skills': 'url2'}) wraps in a list."""
    result = _to_behavior_list({"modes": "url1", "skills": "url2"})
    assert len(result) == 2
    assert {"modes": "url1"} in result
    assert {"skills": "url2"} in result


def test_to_behavior_list_mixed_list() -> None:
    """_to_behavior_list(['local-ref', {'modes': 'url1'}]) handles mixed strings and dicts."""
    result = _to_behavior_list(["local-ref", {"modes": "url1"}])
    assert result == [{"ref": "local-ref"}, {"modes": "url1"}]


# ---------------------------------------------------------------------------
# parse_agent_definition / parse_behavior_definition integration tests
# ---------------------------------------------------------------------------


def test_parse_agent_definition_behaviors_dict_list_format() -> None:
    """parse_agent_definition() preserves alias+url dicts from list-of-dicts behavior format."""
    yaml_content = """\
type: agent
local_ref: my-agent
uuid: 12345678-abcd-ef00-0000-000000000001
behaviors:
  - modes: https://example.com/modes-behavior.yaml
  - skills: https://example.com/skills-behavior.yaml
"""
    result = parse_agent_definition(yaml_content)
    assert result.behaviors == [
        {"modes": "https://example.com/modes-behavior.yaml"},
        {"skills": "https://example.com/skills-behavior.yaml"},
    ]


def test_parse_agent_definition_behaviors_plain_dict_format() -> None:
    """parse_agent_definition() wraps a plain-dict behavior block as a list of alias+url dicts."""
    yaml_content = """\
type: agent
local_ref: my-agent
uuid: 12345678-abcd-ef00-0000-000000000002
behaviors:
  modes: https://example.com/modes-behavior.yaml
"""
    result = parse_agent_definition(yaml_content)
    assert result.behaviors == [{"modes": "https://example.com/modes-behavior.yaml"}]


def test_parse_behavior_definition_behaviors_dict_list_format() -> None:
    """parse_behavior_definition() preserves alias+url dicts from list-of-dicts nested behavior format."""
    yaml_content = """\
type: behavior
local_ref: my-behavior
uuid: abcdefab-0000-0000-0000-000000000001
behaviors:
  - tools: https://example.com/tools-behavior.yaml
  - context: https://example.com/context-behavior.yaml
"""
    result = parse_behavior_definition(yaml_content)
    assert result.behaviors == [
        {"tools": "https://example.com/tools-behavior.yaml"},
        {"context": "https://example.com/context-behavior.yaml"},
    ]


# ---------------------------------------------------------------------------
# resolve_agent integration test with dict-format behaviors
# ---------------------------------------------------------------------------


async def test_resolve_agent_dict_format_behaviors(tmp_path) -> None:
    """resolve_agent() correctly walks behaviors specified in list-of-dicts format."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    # Register a behavior
    behavior_yaml = """\
type: behavior
local_ref: my-behavior
uuid: cccccccc-0000-0000-0000-000000000000
services:
  - stack: uv
    command: behavior-service
"""
    registry.register_definition(behavior_yaml)

    # Agent uses list-of-dicts syntax for behaviors
    agent_yaml = """\
type: agent
local_ref: my-agent
uuid: dddddddd-0000-0000-0000-000000000000
behaviors:
  - mybehav: my-behavior
"""
    registry.register_definition(agent_yaml)

    result = await resolve_agent(registry, "my-agent")

    assert isinstance(result, ResolvedAgent)
    service_commands = [s.command for s in result.services]
    assert "behavior-service" in service_commands


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
  - stack: pip
    command: my-service
"""

    result = parse_agent_definition(yaml_content)

    assert isinstance(result, AgentDefinition)
    assert result.ref == "my-agent"
    assert result.uuid == "12345678-abcd-ef00-0000-000000000000"
    assert result.version == "1"
    assert result.description == "A test agent"
    assert result.orchestrator == "default"
    assert result.provider == "anthropic"
    assert result.behaviors == [{"ref": "some-behavior"}]
    assert result.service is not None
    assert result.service.command == "my-service"
    assert result.service.stack == "pip"


def test_parse_behavior_definition_basic() -> None:
    """parse_behavior_definition() correctly parses a minimal behavior YAML."""
    yaml_content = """\
type: behavior
local_ref: my-behavior
uuid: abcdefab-0000-0000-0000-000000000000
version: 2
description: A test behavior
services:
  - command: behavior-service
    source: https://example.com/service
tools: true
"""

    result = parse_behavior_definition(yaml_content)

    assert isinstance(result, BehaviorDefinition)
    assert result.ref == "my-behavior"
    assert result.uuid == "abcdefab-0000-0000-0000-000000000000"
    assert result.version == "2"
    assert result.description == "A test behavior"
    assert result.service is not None
    assert result.service.command == "behavior-service"
    assert result.service.source == "https://example.com/service"
    assert result.tools is True


async def test_resolve_agent_deduplicates_services(tmp_path) -> None:
    """resolve_agent() deduplicates services by identity across agent and behavior definitions."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    # Register first behavior (shared service, also declared by agent)
    behavior1_yaml = """\
type: behavior
local_ref: shared-behavior
uuid: bbbbbbbb-0000-0000-0000-000000000000
services:
  - stack: pip
    command: shared-service
"""
    registry.register_definition(behavior1_yaml)

    # Register second behavior (unique service)
    behavior2_yaml = """\
type: behavior
local_ref: unique-behavior
uuid: cccccccc-0000-0000-0000-000000000000
services:
  - command: behavior-only-service
"""
    registry.register_definition(behavior2_yaml)

    # Register an agent that also declares the same shared-service and references both behaviors
    agent_yaml = """\
type: agent
local_ref: my-agent
uuid: aaaaaaaa-0000-0000-0000-000000000000
behaviors:
  - shared-behavior
  - unique-behavior
services:
  - stack: pip
    command: shared-service
"""
    registry.register_definition(agent_yaml)

    result = await resolve_agent(registry, "my-agent")

    assert isinstance(result, ResolvedAgent)
    # Services should be deduplicated — shared-service appears once
    service_commands = [s.command for s in result.services]
    assert service_commands.count("shared-service") == 1
    assert "behavior-only-service" in service_commands


def test_parse_agent_definition_tools_bool_true() -> None:
    """parse_agent_definition() handles boolean shorthand (tools: true) as bool True.

    'true' means the capability is enabled — stored as bool True.
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

    assert result.tools is True
    assert result.hooks is True
    assert result.agents is True
    assert result.context is True


def test_parse_agent_definition_tools_bool_false() -> None:
    """parse_agent_definition() handles 'false' booleans — stored as bool False."""
    yaml_content = """\
type: agent
local_ref: my-agent
uuid: 12345678-abcd-ef00-0000-000000000000
tools: false
hooks: false
"""
    result = parse_agent_definition(yaml_content)
    assert result.tools is False
    assert result.hooks is False


def test_parse_behavior_definition_tools_bool_true() -> None:
    """parse_behavior_definition() handles boolean shorthand (tools: true) as bool True."""
    yaml_content = """\
type: behavior
local_ref: my-behavior
uuid: bbbbbbbb-0000-0000-0000-000000000000
tools: true
hooks: true
context: true
"""
    result = parse_behavior_definition(yaml_content)

    assert result.tools is True
    assert result.hooks is True
    assert result.context is True


async def test_resolve_agent_unknown_raises(tmp_path) -> None:
    """resolve_agent() raises FileNotFoundError for an unregistered agent."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    with pytest.raises(FileNotFoundError, match="nonexistent-agent"):
        await resolve_agent(registry, "nonexistent-agent")


def test_agent_definition_has_ref_not_local_ref() -> None:
    """AgentDefinition uses 'ref' instead of 'local_ref' and has no 'type' field."""
    agent = AgentDefinition(ref="my-agent")
    assert agent.ref == "my-agent"
    assert not hasattr(agent, "local_ref"), (
        "AgentDefinition should not have a 'local_ref' attribute"
    )
    assert not hasattr(agent, "type"), (
        "AgentDefinition should not have a 'type' attribute"
    )


def test_behavior_definition_has_ref_not_local_ref() -> None:
    """BehaviorDefinition uses 'ref' instead of 'local_ref' and has no 'type' field."""
    behavior = BehaviorDefinition(ref="my-behavior")
    assert behavior.ref == "my-behavior"
    assert not hasattr(behavior, "local_ref"), (
        "BehaviorDefinition should not have a 'local_ref' attribute"
    )
    assert not hasattr(behavior, "type"), (
        "BehaviorDefinition should not have a 'type' attribute"
    )


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
  - source: ../services/my-service
"""
    definition_path = definitions_dir / "my-agent.yaml"
    definition_path.write_text(yaml_content)

    # Parse with path so relative sources are resolved
    result = parse_agent_definition(yaml_content, path=definition_path)

    assert result.service is not None
    svc = result.service
    assert svc.source is not None
    resolved = Path(svc.source)
    assert resolved.is_absolute(), f"Expected absolute path, got: {svc.source}"
    assert resolved == service_dir.resolve(), (
        f"Expected {service_dir.resolve()}, got {resolved}"
    )
