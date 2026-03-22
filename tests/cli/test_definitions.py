"""Tests for definitions.py - dataclasses and parsing functions for agent/behavior definitions.

NOTE: These tests use the current nested YAML format (agent:/behavior: wrappers) and the
ServiceEntry(stack, source, command) API.  The file was rewritten during task-10 parser
alignment to replace stale tests from the initial merge commit that used the superseded
flat-format / name+installer API.
"""

import asyncio
from pathlib import Path

import pytest

from amplifier_ipc.host.definitions import (
    ResolvedAgent,
    ServiceEntry,
    _parse_service,
    parse_agent_definition,
    parse_behavior_definition,
    resolve_agent,
)


# ---------------------------------------------------------------------------
# Test 1: ServiceEntry construction
# ---------------------------------------------------------------------------
class TestServiceEntry:
    def test_service_entry_construction(self) -> None:
        """ServiceEntry dataclass stores stack, source, command."""
        svc = ServiceEntry(
            stack="uv", source="git+https://example.com/pkg@1.0", command="my-service"
        )

        assert svc.stack == "uv"
        assert svc.source == "git+https://example.com/pkg@1.0"
        assert svc.command == "my-service"

    def test_service_entry_optional_fields(self) -> None:
        """ServiceEntry fields default to None when not provided."""
        svc = ServiceEntry()

        assert svc.stack is None
        assert svc.source is None
        assert svc.command is None


# ---------------------------------------------------------------------------
# Test 2: parse_agent_definition - basic fields (nested format)
# ---------------------------------------------------------------------------
AGENT_BASIC_YAML = """\
agent:
  ref: my-agent
  uuid: 12345678-0000-0000-0000-000000000000
  version: "1.2.3"
  description: A basic test agent
  orchestrator: streaming
  context_manager: simple
  provider: anthropic
"""


class TestParseAgentDefinitionBasicFields:
    def test_parse_agent_basic_fields(self) -> None:
        """parse_agent_definition populates all scalar fields from YAML."""
        defn = parse_agent_definition(AGENT_BASIC_YAML)

        assert defn.ref == "my-agent"
        assert defn.uuid == "12345678-0000-0000-0000-000000000000"
        assert defn.version == "1.2.3"
        assert defn.description == "A basic test agent"
        assert defn.orchestrator == "streaming"
        assert defn.context_manager == "simple"
        assert defn.provider == "anthropic"

    def test_parse_agent_defaults_to_empty_behaviors(self) -> None:
        """parse_agent_definition defaults behaviors to empty list when absent."""
        defn = parse_agent_definition(AGENT_BASIC_YAML)

        assert defn.behaviors == []

    def test_parse_agent_defaults_service_to_none(self) -> None:
        """parse_agent_definition defaults service to None when absent."""
        defn = parse_agent_definition(AGENT_BASIC_YAML)

        assert defn.service is None

    def test_parse_agent_defaults_component_config_to_empty_dict(self) -> None:
        """parse_agent_definition defaults component_config to empty dict when absent."""
        defn = parse_agent_definition(AGENT_BASIC_YAML)

        assert defn.component_config == {}


# ---------------------------------------------------------------------------
# Test 3: parse_agent_definition - behaviors list
# ---------------------------------------------------------------------------
AGENT_WITH_BEHAVIORS_YAML = """\
agent:
  ref: agent-with-behaviors
  behaviors:
    - foundation:explorer
    - foundation:git-ops
    - custom:my-behavior
"""


class TestParseAgentDefinitionBehaviors:
    def test_parse_agent_behaviors(self) -> None:
        """parse_agent_definition populates behaviors list from YAML strings.

        Each plain-string behavior is wrapped as {"ref": value}.
        """
        defn = parse_agent_definition(AGENT_WITH_BEHAVIORS_YAML)

        assert defn.behaviors == [
            {"ref": "foundation:explorer"},
            {"ref": "foundation:git-ops"},
            {"ref": "custom:my-behavior"},
        ]


# ---------------------------------------------------------------------------
# Test 4: parse_agent_definition - singular service block
# ---------------------------------------------------------------------------
AGENT_WITH_SERVICE_YAML = """\
agent:
  ref: agent-with-service
  service:
    stack: uv
    source: git+https://example.com/my-pkg@2.0
    command: my-service
"""


class TestParseAgentDefinitionService:
    def test_parse_agent_service(self) -> None:
        """parse_agent_definition parses singular service: block into ServiceEntry."""
        defn = parse_agent_definition(AGENT_WITH_SERVICE_YAML)

        assert defn.service is not None
        assert isinstance(defn.service, ServiceEntry)
        assert defn.service.stack == "uv"
        assert defn.service.source == "git+https://example.com/my-pkg@2.0"
        assert defn.service.command == "my-service"

    def test_parse_agent_service_partial_fields(self) -> None:
        """parse_agent_definition parses service with only some fields present."""
        yaml_content = """\
agent:
  ref: partial-agent
  service:
    command: just-a-command
"""
        defn = parse_agent_definition(yaml_content)

        assert defn.service is not None
        assert defn.service.command == "just-a-command"
        assert defn.service.stack is None
        assert defn.service.source is None


# ---------------------------------------------------------------------------
# Test 5: parse_behavior_definition - basic fields (nested format)
# ---------------------------------------------------------------------------
BEHAVIOR_BASIC_YAML = """\
behavior:
  ref: my-behavior
  uuid: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
  version: "0.5.0"
  description: A test behavior
"""


class TestParseBehaviorDefinitionBasicFields:
    def test_parse_behavior_basic_fields(self) -> None:
        """parse_behavior_definition populates all scalar fields from YAML."""
        defn = parse_behavior_definition(BEHAVIOR_BASIC_YAML)

        assert defn.ref == "my-behavior"
        assert defn.uuid == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert defn.version == "0.5.0"
        assert defn.description == "A test behavior"

    def test_parse_behavior_defaults_to_empty_collections(self) -> None:
        """parse_behavior_definition defaults list/dict fields to empty when absent."""
        defn = parse_behavior_definition(BEHAVIOR_BASIC_YAML)

        assert defn.behaviors == []
        assert defn.service is None
        assert defn.component_config == {}


# ---------------------------------------------------------------------------
# Test 6: parse_behavior_definition - tools and hooks (bool capability flags)
# ---------------------------------------------------------------------------
BEHAVIOR_TOOLS_HOOKS_YAML = """\
behavior:
  ref: behavior-with-tools-hooks
  tools: true
  hooks: true
"""


class TestParseBehaviorDefinitionToolsHooks:
    def test_parse_behavior_tools_and_hooks(self) -> None:
        """parse_behavior_definition parses tools and hooks as boolean capability flags."""
        defn = parse_behavior_definition(BEHAVIOR_TOOLS_HOOKS_YAML)

        assert defn.tools is True
        assert defn.hooks is True

    def test_parse_behavior_tools_absent_defaults_false(self) -> None:
        """parse_behavior_definition defaults tools/hooks to False when absent."""
        defn = parse_behavior_definition(BEHAVIOR_BASIC_YAML)

        assert defn.tools is False
        assert defn.hooks is False


# ---------------------------------------------------------------------------
# Test 7: parse_behavior_definition - nested behaviors
# ---------------------------------------------------------------------------
BEHAVIOR_NESTED_YAML = """\
behavior:
  ref: behavior-with-nested
  behaviors:
    - foundation:explorer
    - foundation:file-ops
"""


class TestParseBehaviorDefinitionNestedBehaviors:
    def test_parse_behavior_nested_behaviors(self) -> None:
        """parse_behavior_definition parses nested behaviors list."""
        defn = parse_behavior_definition(BEHAVIOR_NESTED_YAML)

        assert defn.behaviors == [
            {"ref": "foundation:explorer"},
            {"ref": "foundation:file-ops"},
        ]


# ---------------------------------------------------------------------------
# Test 8: parse_behavior_definition - singular service block
# ---------------------------------------------------------------------------
BEHAVIOR_WITH_SERVICE_YAML = """\
behavior:
  ref: behavior-with-service
  service:
    stack: uv
    command: agent-browser
    source: git+https://example.com/agent-browser@latest
"""


class TestParseBehaviorDefinitionService:
    def test_parse_behavior_service(self) -> None:
        """parse_behavior_definition parses service: block into ServiceEntry."""
        defn = parse_behavior_definition(BEHAVIOR_WITH_SERVICE_YAML)

        assert defn.service is not None
        assert isinstance(defn.service, ServiceEntry)
        assert defn.service.stack == "uv"
        assert defn.service.command == "agent-browser"
        assert defn.service.source == "git+https://example.com/agent-browser@latest"


# ---------------------------------------------------------------------------
# Additional: _parse_service helper behaviour
# ---------------------------------------------------------------------------
class TestParseServiceHelper:
    def test_parse_service_returns_none_for_none(self) -> None:
        """_parse_service returns None for None input."""
        assert _parse_service(None) is None

    def test_parse_service_returns_none_for_list(self) -> None:
        """_parse_service returns None for list input (not a dict)."""
        assert _parse_service([{"stack": "uv"}]) is None

    def test_parse_service_returns_none_for_string(self) -> None:
        """_parse_service returns None for string input."""
        assert _parse_service("uv") is None

    def test_parse_service_returns_service_entry_for_dict(self) -> None:
        """_parse_service returns ServiceEntry for a valid dict."""
        result = _parse_service(
            {"stack": "uv", "source": "git+https://x.com/y", "command": "cmd"}
        )
        assert isinstance(result, ServiceEntry)
        assert result.stack == "uv"
        assert result.source == "git+https://x.com/y"
        assert result.command == "cmd"

    def test_parse_service_partial_fields_default_to_none(self) -> None:
        """_parse_service sets missing fields to None."""
        result = _parse_service({"command": "only-command"})
        assert isinstance(result, ServiceEntry)
        assert result.command == "only-command"
        assert result.stack is None
        assert result.source is None


# ---------------------------------------------------------------------------
# Additional: ResolvedAgent exists as a dataclass with tuple-based services
# ---------------------------------------------------------------------------
class TestResolvedAgentExists:
    def test_resolved_agent_can_be_constructed(self) -> None:
        """ResolvedAgent dataclass exists and can be constructed with (ref, ServiceEntry) tuples."""
        svc = ServiceEntry(stack="uv", command="my-service")
        resolved = ResolvedAgent(
            services=[("my-agent", svc)],
            orchestrator="streaming",
            context_manager="simple",
            provider="anthropic",
            component_config={"key": "value"},
        )

        assert len(resolved.services) == 1
        ref, entry = resolved.services[0]
        assert ref == "my-agent"
        assert entry is svc
        assert resolved.orchestrator == "streaming"
        assert resolved.context_manager == "simple"
        assert resolved.provider == "anthropic"
        assert resolved.component_config == {"key": "value"}

    def test_resolved_agent_multiple_services(self) -> None:
        """ResolvedAgent stores multiple (ref, ServiceEntry) tuples."""
        svc1 = ServiceEntry(stack="uv", command="service-a")
        svc2 = ServiceEntry(command="service-b")
        resolved = ResolvedAgent(
            services=[("ref-a", svc1), ("ref-b", svc2)],
        )

        refs = [ref for ref, _ in resolved.services]
        assert refs == ["ref-a", "ref-b"]


# ---------------------------------------------------------------------------
# Test suite: resolve_agent() tree walking
# ---------------------------------------------------------------------------

# YAML definitions for a 3-level hierarchy:
#   agent "my-test-agent"
#     -> behavior "amplifier-dev" (which includes a service + nested behavior)
#        -> behavior "design-intelligence"

_AGENT_YAML = """\
agent:
  ref: my-test-agent
  uuid: 11111111-0000-0000-0000-000000000001
  orchestrator: streaming
  context_manager: simple
  provider: anthropic
  component_config:
    key: value
  service:
    stack: uv
    command: agent-foundation
  behaviors:
    - amplifier-dev
"""

_AMPLIFIER_DEV_BEHAVIOR_YAML = """\
behavior:
  ref: amplifier-dev
  uuid: 22222222-0000-0000-0000-000000000002
  service:
    stack: uv
    command: amplifier-dev-cmd
  behaviors:
    - design-intelligence
"""

_DESIGN_INTELLIGENCE_BEHAVIOR_YAML = """\
behavior:
  ref: design-intelligence
  uuid: 33333333-0000-0000-0000-000000000003
  service:
    stack: uv
    command: design-intelligence-cmd
"""


def _setup_registry_with_definitions(tmp_path: Path):
    """Create a 3-level hierarchy: agent -> amplifier-dev -> design-intelligence.

    Returns a configured Registry instance.
    """
    from amplifier_ipc.host.definition_registry import Registry

    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()
    registry.register_definition(_AGENT_YAML)
    registry.register_definition(_AMPLIFIER_DEV_BEHAVIOR_YAML)
    registry.register_definition(_DESIGN_INTELLIGENCE_BEHAVIOR_YAML)
    return registry


class TestResolveAgentTreeWalking:
    def test_resolve_agent_basic(self, tmp_path: Path) -> None:
        """resolve_agent() returns a ResolvedAgent with correct scalar fields."""
        registry = _setup_registry_with_definitions(tmp_path)

        resolved = asyncio.run(resolve_agent(registry, "my-test-agent"))

        assert isinstance(resolved, ResolvedAgent)
        assert resolved.orchestrator == "streaming"
        assert resolved.context_manager == "simple"
        assert resolved.provider == "anthropic"
        assert resolved.component_config == {"key": "value"}

    def test_resolve_agent_collects_services_from_tree(self, tmp_path: Path) -> None:
        """resolve_agent() collects services from agent and all nested behaviors."""
        registry = _setup_registry_with_definitions(tmp_path)

        resolved = asyncio.run(resolve_agent(registry, "my-test-agent"))

        # agent + amplifier-dev + design-intelligence each contribute a service
        assert len(resolved.services) == 3
        service_refs = [ref for ref, _ in resolved.services]
        assert "my-test-agent" in service_refs
        assert "amplifier-dev" in service_refs
        assert "design-intelligence" in service_refs

    def test_resolve_agent_deduplicates_services_by_ref(self, tmp_path: Path) -> None:
        """Services are deduplicated by ref even when referenced via multiple paths."""
        from amplifier_ipc.host.definition_registry import Registry

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        shared_yaml = """\
behavior:
  ref: shared-behavior
  uuid: aaaaaaaa-0000-0000-0000-000000000000
  service:
    command: shared-service
"""
        wrapper_yaml = """\
behavior:
  ref: wrapper-behavior
  uuid: bbbbbbbb-0000-0000-0000-000000000000
  behaviors:
    - shared-behavior
"""
        agent_yaml = """\
agent:
  ref: my-dedup-agent
  uuid: cccccccc-0000-0000-0000-000000000000
  behaviors:
    - wrapper-behavior
    - shared-behavior
"""
        registry.register_definition(shared_yaml)
        registry.register_definition(wrapper_yaml)
        registry.register_definition(agent_yaml)

        resolved = asyncio.run(resolve_agent(registry, "my-dedup-agent"))

        service_refs = [ref for ref, _ in resolved.services]
        assert service_refs.count("shared-behavior") == 1, (
            "shared-behavior declared via two paths but should appear only once"
        )

    def test_resolve_agent_with_extra_behaviors(self, tmp_path: Path) -> None:
        """Extra behaviors passed to resolve_agent() are merged into the result."""
        from amplifier_ipc.host.definition_registry import Registry

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        simple_agent_yaml = """\
agent:
  ref: simple-agent
  uuid: 44444444-0000-0000-0000-000000000004
"""
        extra_behavior_yaml = """\
behavior:
  ref: extra-behavior
  uuid: 55555555-0000-0000-0000-000000000005
  service:
    stack: uv
    command: extra-cmd
"""
        registry.register_definition(simple_agent_yaml)
        registry.register_definition(extra_behavior_yaml)

        resolved = asyncio.run(
            resolve_agent(registry, "simple-agent", extra_behaviors=["extra-behavior"])
        )

        service_refs = [ref for ref, _ in resolved.services]
        assert "extra-behavior" in service_refs

    def test_resolve_agent_unknown_agent_raises(self, tmp_path: Path) -> None:
        """resolve_agent() raises FileNotFoundError for an agent not in the registry."""
        from amplifier_ipc.host.definition_registry import Registry

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        with pytest.raises(FileNotFoundError):
            asyncio.run(resolve_agent(registry, "nonexistent-agent"))


# ---------------------------------------------------------------------------
# Test suite: resolve_agent() URL fetching
# ---------------------------------------------------------------------------

_REMOTE_BEHAVIOR_YAML = """\
behavior:
  ref: remote-service-behavior
  uuid: 88888888-0000-0000-0000-000000000008
  service:
    stack: uv
    command: remote-service
"""

_AGENT_WITH_URL_BEHAVIOR_YAML = """\
agent:
  ref: url-test-agent
  uuid: 99999999-0000-0000-0000-000000000009
  behaviors:
    - https://example.com/behaviors/remote-behavior.yaml
"""


class TestResolveAgentURLFetching:
    def test_resolve_agent_fetches_url_behavior(self, tmp_path: Path) -> None:
        """resolve_agent() fetches and auto-registers URL behaviors not found locally."""
        from unittest.mock import AsyncMock, patch

        from amplifier_ipc.host.definition_registry import Registry

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()
        registry.register_definition(_AGENT_WITH_URL_BEHAVIOR_YAML)

        url = "https://example.com/behaviors/remote-behavior.yaml"

        with patch(
            "amplifier_ipc.host.definitions._fetch_url", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _REMOTE_BEHAVIOR_YAML

            resolved = asyncio.run(resolve_agent(registry, "url-test-agent"))

        # Remote service should be included in resolved services (keyed by ref).
        service_refs = [ref for ref, _ in resolved.services]
        assert "remote-service-behavior" in service_refs

        # _fetch_url must have been called with the correct URL.
        mock_fetch.assert_called_once_with(url)

        # Behavior should now be registered locally (resolvable by URL alias).
        behavior_path = registry.resolve_behavior(url)
        assert behavior_path.exists()

    def test_resolve_agent_uses_cached_behavior_on_second_call(
        self, tmp_path: Path
    ) -> None:
        """Second resolve_agent() call uses the cached local copy without re-fetching."""
        from unittest.mock import AsyncMock, patch

        from amplifier_ipc.host.definition_registry import Registry

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()
        registry.register_definition(_AGENT_WITH_URL_BEHAVIOR_YAML)

        with patch(
            "amplifier_ipc.host.definitions._fetch_url", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _REMOTE_BEHAVIOR_YAML

            # First call – should fetch the remote behavior.
            asyncio.run(resolve_agent(registry, "url-test-agent"))
            assert mock_fetch.call_count == 1

            # Second call – should NOT fetch again; uses the registered copy.
            asyncio.run(resolve_agent(registry, "url-test-agent"))
            assert mock_fetch.call_count == 1, (
                "Second resolve must not re-fetch URL behavior"
            )
