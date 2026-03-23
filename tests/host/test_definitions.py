"""Tests for the definitions module (moved from amplifier-ipc-cli)."""

from __future__ import annotations

import pytest

from amplifier_ipc.host.definitions import (
    AgentDefinition,
    BehaviorDefinition,
    ResolvedAgent,
    ServiceEntry,
    _parse_service,
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
# _parse_service unit tests
# ---------------------------------------------------------------------------


def test_parse_service_returns_service_entry() -> None:
    """_parse_service() returns a ServiceEntry when given a dict with service fields."""
    data = {"stack": "uv", "source": "git+https://example.com/pkg", "command": "serve"}
    svc = _parse_service(data)
    assert isinstance(svc, ServiceEntry)
    assert svc.stack == "uv"
    assert svc.source == "git+https://example.com/pkg"
    assert svc.command == "serve"


def test_parse_service_returns_none_for_none() -> None:
    """_parse_service() returns None for non-dict inputs (None, list, string)."""
    assert _parse_service(None) is None
    assert _parse_service([{"stack": "uv"}]) is None
    assert _parse_service("string") is None
    assert _parse_service(True) is None


# ---------------------------------------------------------------------------
# parse_agent_definition tests (nested format)
# ---------------------------------------------------------------------------


def test_parse_agent_definition_nested_format() -> None:
    """parse_agent_definition() reads all fields from nested agent: block."""
    yaml_content = """\
agent:
  ref: my-agent
  uuid: 12345678-abcd-ef00-0000-000000000000
  version: 1
  description: A test agent
  orchestrator: foundation:streaming
  context_manager: foundation:simple
  provider: anthropic
  tools: true
  hooks: true
  agents: true
  context: true
  behaviors:
    - some-behavior
  service:
    stack: uv
    command: my-service
"""
    result = parse_agent_definition(yaml_content)
    assert isinstance(result, AgentDefinition)
    assert result.ref == "my-agent"
    assert result.uuid == "12345678-abcd-ef00-0000-000000000000"
    assert result.version == "1"
    assert result.description == "A test agent"
    assert result.orchestrator == "foundation:streaming"
    assert result.context_manager == "foundation:simple"
    assert result.provider == "anthropic"
    assert result.tools is True
    assert result.hooks is True
    assert result.agents is True
    assert result.context is True
    assert result.behaviors == [{"ref": "some-behavior"}]
    assert result.service is not None
    assert result.service.stack == "uv"
    assert result.service.command == "my-service"


def test_parse_agent_definition_no_service() -> None:
    """parse_agent_definition() sets service=None when no service block present."""
    yaml_content = """\
agent:
  ref: my-agent
  uuid: 12345678-abcd-ef00-0000-000000000000
"""
    result = parse_agent_definition(yaml_content)
    assert result.service is None


def test_parse_agent_definition_empty_behaviors() -> None:
    """parse_agent_definition() returns empty behaviors list when behaviors not specified."""
    yaml_content = """\
agent:
  ref: my-agent
"""
    result = parse_agent_definition(yaml_content)
    assert result.behaviors == []


def test_parse_agent_definition_with_config() -> None:
    """parse_agent_definition() reads component_config from the component_config: key."""
    yaml_content = """\
agent:
  ref: my-agent
  component_config:
    model: gpt-4
    temperature: 0.7
"""
    result = parse_agent_definition(yaml_content)
    assert result.component_config == {"model": "gpt-4", "temperature": 0.7}


# ---------------------------------------------------------------------------
# parse_behavior_definition tests (nested format)
# ---------------------------------------------------------------------------


def test_parse_behavior_definition_nested_format() -> None:
    """parse_behavior_definition() reads all fields from nested behavior: block."""
    yaml_content = """\
behavior:
  ref: my-behavior
  uuid: abcdefab-0000-0000-0000-000000000000
  version: 2
  description: A test behavior
  tools: true
  hooks: true
  context: true
  service:
    stack: uv
    source: https://example.com/service
    command: behavior-service
"""
    result = parse_behavior_definition(yaml_content)
    assert isinstance(result, BehaviorDefinition)
    assert result.ref == "my-behavior"
    assert result.uuid == "abcdefab-0000-0000-0000-000000000000"
    assert result.version == "2"
    assert result.description == "A test behavior"
    assert result.tools is True
    assert result.hooks is True
    assert result.context is True
    assert result.service is not None
    assert result.service.stack == "uv"
    assert result.service.source == "https://example.com/service"
    assert result.service.command == "behavior-service"


def test_parse_behavior_definition_no_service() -> None:
    """parse_behavior_definition() sets service=None when no service block present."""
    yaml_content = """\
behavior:
  ref: my-behavior
"""
    result = parse_behavior_definition(yaml_content)
    assert result.service is None


def test_parse_behavior_definition_with_config() -> None:
    """parse_behavior_definition() reads component_config from the config: key."""
    yaml_content = """\
behavior:
  ref: my-behavior
  config:
    timeout: 30
    retries: 3
"""
    result = parse_behavior_definition(yaml_content)
    assert result.component_config == {"timeout": 30, "retries": 3}


def test_parse_behavior_definition_with_sub_behaviors() -> None:
    """parse_behavior_definition() parses nested behaviors list-of-dicts correctly."""
    yaml_content = """\
behavior:
  ref: my-behavior
  behaviors:
    - tools: https://example.com/tools.yaml
    - context: https://example.com/context.yaml
"""
    result = parse_behavior_definition(yaml_content)
    assert result.behaviors == [
        {"tools": "https://example.com/tools.yaml"},
        {"context": "https://example.com/context.yaml"},
    ]


# ---------------------------------------------------------------------------
# resolve_agent integration tests
# ---------------------------------------------------------------------------


async def test_resolve_agent_walks_behavior_tree(tmp_path) -> None:
    """resolve_agent() walks the behavior tree and collects services from both agent and behavior."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    # Register a behavior with its own service
    behavior_yaml = """\
behavior:
  ref: my-behavior
  uuid: cccccccc-0000-0000-0000-000000000000
  service:
    stack: uv
    command: behavior-service
"""
    registry.register_definition(behavior_yaml)

    # Register agent with its own service, referencing the behavior
    agent_yaml = """\
agent:
  ref: my-agent
  uuid: dddddddd-0000-0000-0000-000000000000
  service:
    stack: uv
    command: agent-service
  behaviors:
    - my-behavior
"""
    registry.register_definition(agent_yaml)

    result = await resolve_agent(registry, "my-agent")

    assert isinstance(result, ResolvedAgent)
    # Both agent and behavior contribute a service → 2 total
    assert len(result.services) == 2
    service_refs = [ref for ref, _ in result.services]
    assert "my-agent" in service_refs
    assert "my-behavior" in service_refs


async def test_resolve_agent_deduplicates_by_ref(tmp_path) -> None:
    """resolve_agent() does not duplicate a behavior's service when referenced multiple times."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    # Register a shared behavior with a service
    shared_yaml = """\
behavior:
  ref: shared-behavior
  uuid: aaaaaaaa-0000-0000-0000-000000000000
  service:
    command: shared-service
"""
    registry.register_definition(shared_yaml)

    # Register a wrapper behavior that also references shared-behavior
    wrapper_yaml = """\
behavior:
  ref: wrapper-behavior
  uuid: bbbbbbbb-0000-0000-0000-000000000000
  behaviors:
    - shared-behavior
"""
    registry.register_definition(wrapper_yaml)

    # Agent references wrapper-behavior AND shared-behavior directly
    agent_yaml = """\
agent:
  ref: my-agent
  uuid: cccccccc-0000-0000-0000-000000000000
  behaviors:
    - wrapper-behavior
    - shared-behavior
"""
    registry.register_definition(agent_yaml)

    result = await resolve_agent(registry, "my-agent")

    assert isinstance(result, ResolvedAgent)
    # shared-behavior service must appear exactly once (deduplicated by ref)
    service_refs = [ref for ref, _ in result.services]
    assert service_refs.count("shared-behavior") == 1


async def test_resolve_agent_merges_config(tmp_path) -> None:
    """resolve_agent() merges config: behavior provides defaults, agent wins at key level."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    # Behavior has gate_policy:warn and verbose:true in its config
    behavior_yaml = """\
behavior:
  ref: my-behavior
  uuid: eeeeeeee-0000-0000-0000-000000000000
  service:
    command: behavior-service
  config:
    gate_policy: warn
    verbose: true
"""
    registry.register_definition(behavior_yaml)

    # Agent overrides gate_policy to "block" for "my-behavior" service via prefixed key
    agent_yaml = """\
agent:
  ref: my-agent
  uuid: ffffffff-0000-0000-0000-000000000000
  behaviors:
    - my-behavior
  component_config:
    my-behavior:gate_policy: block
"""
    registry.register_definition(agent_yaml)

    result = await resolve_agent(registry, "my-agent")

    assert isinstance(result, ResolvedAgent)
    merged = result.service_configs.get("my-behavior", {})
    # Agent wins on gate_policy (block overrides warn)
    assert merged.get("gate_policy") == "block"
    # verbose:true from behavior is preserved (agent didn't override it)
    assert merged.get("verbose") is True


async def test_resolve_agent_unknown_raises(tmp_path) -> None:
    """resolve_agent() raises FileNotFoundError for an unregistered agent."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    with pytest.raises(FileNotFoundError, match="nonexistent-agent"):
        await resolve_agent(registry, "nonexistent-agent")


async def test_resolve_agent_url_behavior_falls_back_to_local_alias(
    tmp_path,
) -> None:
    """resolve_agent() resolves URL-referenced behaviors via local alias fallback.

    In the real definition format, agent behaviors are listed as {alias: url}:

        behaviors:
          - modes: https://raw.githubusercontent.com/.../modes.yaml

    When 'modes' is registered locally (by ref) but NOT under the URL, the
    _walk_behavior logic must try the local alias (key) before giving up.

    This simulates the local dev workflow where discover --register populates
    behaviors by ref, but the agent definition references them by URL.
    """
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    # Register the 'modes' behavior locally by its ref (as discover --register does)
    modes_yaml = """\
behavior:
  ref: modes
  uuid: bbbbbbbb-0000-0000-0000-000000000001
  description: Mode system
  service:
    stack: uv
    command: amplifier-modes-serve
"""
    registry.register_definition(modes_yaml)

    # Agent references 'modes' via a URL (not the local ref) - this is the real format
    agent_yaml = """\
agent:
  ref: url-agent
  uuid: cccccccc-0000-0000-0000-000000000001
  orchestrator: streaming
  context_manager: simple
  provider: anthropic
  behaviors:
    - modes: https://raw.githubusercontent.com/fake/repo/main/modes.yaml
"""
    registry.register_definition(agent_yaml)

    # This should resolve successfully, finding 'modes' via the local alias 'modes'
    result = await resolve_agent(registry, "url-agent")

    assert isinstance(result, ResolvedAgent)
    # The 'modes' behavior should be in services (found via local alias fallback)
    service_refs = [ref for ref, _ in result.services]
    assert "modes" in service_refs, (
        f"Expected 'modes' in resolved services {service_refs}. "
        "URL-referenced behaviors must fall back to local alias when URL is not in registry."
    )


# ---------------------------------------------------------------------------
# Dataclass structure tests
# ---------------------------------------------------------------------------


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
