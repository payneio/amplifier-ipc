"""Tests for definitions.py - dataclasses and parsing functions for agent/behavior definitions."""

import asyncio
from pathlib import Path

import pytest

from amplifier_ipc_cli.definitions import (
    ResolvedAgent,
    ServiceEntry,
    _parse_services,
    parse_agent_definition,
    parse_behavior_definition,
    resolve_agent,
)


# ---------------------------------------------------------------------------
# Test 1: ServiceEntry construction
# ---------------------------------------------------------------------------
class TestServiceEntry:
    def test_service_entry_construction(self) -> None:
        """ServiceEntry dataclass stores name, installer, source."""
        svc = ServiceEntry(
            name="my-service", installer="npm", source="npm:my-service@1.0"
        )

        assert svc.name == "my-service"
        assert svc.installer == "npm"
        assert svc.source == "npm:my-service@1.0"

    def test_service_entry_optional_fields(self) -> None:
        """ServiceEntry fields can be None when not provided."""
        svc = ServiceEntry(name="svc")

        assert svc.name == "svc"
        assert svc.installer is None
        assert svc.source is None


# ---------------------------------------------------------------------------
# Test 2: parse_agent_definition - basic fields
# ---------------------------------------------------------------------------
AGENT_BASIC_YAML = """\
type: agent
local_ref: my-agent
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

        assert defn.type == "agent"
        assert defn.local_ref == "my-agent"
        assert defn.uuid == "12345678-0000-0000-0000-000000000000"
        assert defn.version == "1.2.3"
        assert defn.description == "A basic test agent"
        assert defn.orchestrator == "streaming"
        assert defn.context_manager == "simple"
        assert defn.provider == "anthropic"

    def test_parse_agent_defaults_to_empty_lists(self) -> None:
        """parse_agent_definition defaults list fields to empty lists when absent."""
        defn = parse_agent_definition(AGENT_BASIC_YAML)

        assert defn.behaviors == []
        assert defn.services == []
        assert defn.tools == []
        assert defn.hooks == []
        assert defn.agents == []

    def test_parse_agent_defaults_context_and_component_config(self) -> None:
        """parse_agent_definition defaults dict fields to empty dicts when absent."""
        defn = parse_agent_definition(AGENT_BASIC_YAML)

        assert defn.context == {}
        assert defn.component_config == {}


# ---------------------------------------------------------------------------
# Test 3: parse_agent_definition - behaviors list
# ---------------------------------------------------------------------------
AGENT_WITH_BEHAVIORS_YAML = """\
type: agent
local_ref: agent-with-behaviors
behaviors:
  - foundation:explorer
  - foundation:git-ops
  - custom:my-behavior
"""


class TestParseAgentDefinitionBehaviors:
    def test_parse_agent_behaviors(self) -> None:
        """parse_agent_definition populates behaviors list from YAML."""
        defn = parse_agent_definition(AGENT_WITH_BEHAVIORS_YAML)

        assert defn.behaviors == [
            "foundation:explorer",
            "foundation:git-ops",
            "custom:my-behavior",
        ]


# ---------------------------------------------------------------------------
# Test 4: parse_agent_definition - services list
# ---------------------------------------------------------------------------
AGENT_WITH_SERVICES_YAML = """\
type: agent
local_ref: agent-with-services
services:
  - name: my-npm-package
    installer: npm
    source: "npm:my-npm-package@2.0"
  - name: local-tool
    installer: pip
"""


class TestParseAgentDefinitionServices:
    def test_parse_agent_services(self) -> None:
        """parse_agent_definition parses services into ServiceEntry list."""
        defn = parse_agent_definition(AGENT_WITH_SERVICES_YAML)

        assert len(defn.services) == 2
        assert isinstance(defn.services[0], ServiceEntry)
        assert defn.services[0].name == "my-npm-package"
        assert defn.services[0].installer == "npm"
        assert defn.services[0].source == "npm:my-npm-package@2.0"

        assert isinstance(defn.services[1], ServiceEntry)
        assert defn.services[1].name == "local-tool"
        assert defn.services[1].installer == "pip"
        assert defn.services[1].source is None


# ---------------------------------------------------------------------------
# Test 5: parse_behavior_definition - basic fields
# ---------------------------------------------------------------------------
BEHAVIOR_BASIC_YAML = """\
type: behavior
local_ref: my-behavior
uuid: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
version: "0.5.0"
description: A test behavior
"""


class TestParseBehaviorDefinitionBasicFields:
    def test_parse_behavior_basic_fields(self) -> None:
        """parse_behavior_definition populates all scalar fields from YAML."""
        defn = parse_behavior_definition(BEHAVIOR_BASIC_YAML)

        assert defn.type == "behavior"
        assert defn.local_ref == "my-behavior"
        assert defn.uuid == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert defn.version == "0.5.0"
        assert defn.description == "A test behavior"

    def test_parse_behavior_defaults_to_empty_collections(self) -> None:
        """parse_behavior_definition defaults list/dict fields to empty when absent."""
        defn = parse_behavior_definition(BEHAVIOR_BASIC_YAML)

        assert defn.behaviors == []
        assert defn.services == []
        assert defn.tools == []
        assert defn.hooks == []
        assert defn.context == {}


# ---------------------------------------------------------------------------
# Test 6: parse_behavior_definition - tools and hooks
# ---------------------------------------------------------------------------
BEHAVIOR_TOOLS_HOOKS_YAML = """\
type: behavior
local_ref: behavior-with-tools-hooks
tools:
  - bash
  - read_file
  - write_file
hooks:
  - pre_request
  - post_response
"""


class TestParseBehaviorDefinitionToolsHooks:
    def test_parse_behavior_tools_and_hooks(self) -> None:
        """parse_behavior_definition parses tools and hooks lists correctly."""
        defn = parse_behavior_definition(BEHAVIOR_TOOLS_HOOKS_YAML)

        assert defn.tools == ["bash", "read_file", "write_file"]
        assert defn.hooks == ["pre_request", "post_response"]


# ---------------------------------------------------------------------------
# Test 7: parse_behavior_definition - nested behaviors
# ---------------------------------------------------------------------------
BEHAVIOR_NESTED_YAML = """\
type: behavior
local_ref: behavior-with-nested
behaviors:
  - foundation:explorer
  - foundation:file-ops
"""


class TestParseBehaviorDefinitionNestedBehaviors:
    def test_parse_behavior_nested_behaviors(self) -> None:
        """parse_behavior_definition parses nested behaviors list."""
        defn = parse_behavior_definition(BEHAVIOR_NESTED_YAML)

        assert defn.behaviors == ["foundation:explorer", "foundation:file-ops"]


# ---------------------------------------------------------------------------
# Test 8: parse_behavior_definition - services
# ---------------------------------------------------------------------------
BEHAVIOR_WITH_SERVICES_YAML = """\
type: behavior
local_ref: behavior-with-services
services:
  - name: agent-browser
    installer: npm
    source: "npm:agent-browser@latest"
"""


class TestParseBehaviorDefinitionServices:
    def test_parse_behavior_services(self) -> None:
        """parse_behavior_definition parses services into ServiceEntry list."""
        defn = parse_behavior_definition(BEHAVIOR_WITH_SERVICES_YAML)

        assert len(defn.services) == 1
        assert isinstance(defn.services[0], ServiceEntry)
        assert defn.services[0].name == "agent-browser"
        assert defn.services[0].installer == "npm"
        assert defn.services[0].source == "npm:agent-browser@latest"


# ---------------------------------------------------------------------------
# Additional: _parse_services raises on missing name key
# ---------------------------------------------------------------------------
class TestParseServicesMissingName:
    def test_parse_services_missing_name_raises_key_error(self) -> None:
        """_parse_services raises KeyError when a service dict has no 'name' key."""
        with pytest.raises(KeyError):
            _parse_services([{"installer": "npm", "source": "npm:thing@1.0"}])


# ---------------------------------------------------------------------------
# Additional: ResolvedAgent exists as a dataclass
# ---------------------------------------------------------------------------
class TestResolvedAgentExists:
    def test_resolved_agent_can_be_constructed(self) -> None:
        """ResolvedAgent dataclass exists and can be constructed."""
        svc = ServiceEntry(name="my-service", installer="npm")
        resolved = ResolvedAgent(
            services=[svc],
            orchestrator="streaming",
            context_manager="simple",
            provider="anthropic",
            component_config={"key": "value"},
        )

        assert resolved.services == [svc]
        assert resolved.orchestrator == "streaming"
        assert resolved.context_manager == "simple"
        assert resolved.provider == "anthropic"
        assert resolved.component_config == {"key": "value"}


# ---------------------------------------------------------------------------
# Test suite: resolve_agent() tree walking
# ---------------------------------------------------------------------------

# YAML definitions for a 3-level hierarchy:
#   agent "my-test-agent"
#     -> behavior "amplifier-dev" (which includes services + nested behavior)
#        -> behavior "design-intelligence"
# Each level declares the "amplifier-foundation" service (dedup test).

_AGENT_YAML = """\
type: agent
local_ref: my-test-agent
uuid: 11111111-0000-0000-0000-000000000001
orchestrator: streaming
context_manager: simple
provider: anthropic
component_config:
  key: value
behaviors:
  - amplifier-dev
services:
  - name: amplifier-foundation
    installer: pip
    source: pip:amplifier-foundation@latest
"""

_AMPLIFIER_DEV_BEHAVIOR_YAML = """\
type: behavior
local_ref: amplifier-dev
uuid: 22222222-0000-0000-0000-000000000002
behaviors:
  - design-intelligence
services:
  - name: amplifier-foundation
    installer: pip
    source: pip:amplifier-foundation@latest
"""

_DESIGN_INTELLIGENCE_BEHAVIOR_YAML = """\
type: behavior
local_ref: design-intelligence
uuid: 33333333-0000-0000-0000-000000000003
services:
  - name: amplifier-foundation
    installer: pip
    source: pip:amplifier-foundation@latest
"""


def _setup_registry_with_definitions(tmp_path: Path):
    """Create a 3-level hierarchy: agent -> amplifier-dev -> design-intelligence.

    Each level declares 'amplifier-foundation' as a service.
    Returns a configured Registry instance.
    """
    from amplifier_ipc_cli.registry import Registry

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

    def test_resolve_agent_deduplicates_services(self, tmp_path: Path) -> None:
        """Services are deduplicated by name even when declared in agent + 2 behaviors."""
        registry = _setup_registry_with_definitions(tmp_path)

        resolved = asyncio.run(resolve_agent(registry, "my-test-agent"))

        service_names = [s.name for s in resolved.services]
        assert service_names.count("amplifier-foundation") == 1, (
            "amplifier-foundation declared in 3 definitions but should appear only once"
        )

    def test_resolve_agent_walks_nested_behaviors(self, tmp_path: Path) -> None:
        """resolve_agent() recursively resolves nested behaviors collecting their services."""
        registry = _setup_registry_with_definitions(tmp_path)

        resolved = asyncio.run(resolve_agent(registry, "my-test-agent"))

        # The only unique service across all 3 levels is amplifier-foundation
        assert len(resolved.services) == 1
        assert resolved.services[0].name == "amplifier-foundation"
        assert resolved.services[0].installer == "pip"

    def test_resolve_agent_with_extra_behaviors(self, tmp_path: Path) -> None:
        """Extra behaviors passed to resolve_agent() are merged into the result."""
        from amplifier_ipc_cli.registry import Registry

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        # A simple agent with no behaviors/services
        simple_agent_yaml = """\
type: agent
local_ref: simple-agent
uuid: 44444444-0000-0000-0000-000000000004
"""
        # An extra behavior that brings in a unique service
        extra_behavior_yaml = """\
type: behavior
local_ref: extra-behavior
uuid: 55555555-0000-0000-0000-000000000005
services:
  - name: extra-service
    installer: npm
"""
        registry.register_definition(simple_agent_yaml)
        registry.register_definition(extra_behavior_yaml)

        resolved = asyncio.run(
            resolve_agent(registry, "simple-agent", extra_behaviors=["extra-behavior"])
        )

        service_names = [s.name for s in resolved.services]
        assert "extra-service" in service_names

    def test_resolve_agent_unknown_agent_raises(self, tmp_path: Path) -> None:
        """resolve_agent() raises FileNotFoundError for an agent not in the registry."""
        from amplifier_ipc_cli.registry import Registry

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        with pytest.raises(FileNotFoundError):
            asyncio.run(resolve_agent(registry, "nonexistent-agent"))


# ---------------------------------------------------------------------------
# Test suite: resolve_agent() URL fetching
# ---------------------------------------------------------------------------

_REMOTE_BEHAVIOR_YAML = """\
type: behavior
local_ref: remote-service-behavior
uuid: 88888888-0000-0000-0000-000000000008
services:
  - name: remote-service
    installer: npm
    source: npm:remote-service@1.0
"""

_AGENT_WITH_URL_BEHAVIOR_YAML = """\
type: agent
local_ref: url-test-agent
uuid: 99999999-0000-0000-0000-000000000009
behaviors:
  - https://example.com/behaviors/remote-behavior.yaml
"""


class TestResolveAgentURLFetching:
    def test_resolve_agent_fetches_url_behavior(self, tmp_path: Path) -> None:
        """resolve_agent() fetches and auto-registers URL behaviors not found locally."""
        from unittest.mock import AsyncMock, patch

        from amplifier_ipc_cli.registry import Registry

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()
        registry.register_definition(_AGENT_WITH_URL_BEHAVIOR_YAML)

        url = "https://example.com/behaviors/remote-behavior.yaml"

        with patch(
            "amplifier_ipc_cli.definitions._fetch_url", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = _REMOTE_BEHAVIOR_YAML

            resolved = asyncio.run(resolve_agent(registry, "url-test-agent"))

        # Remote service should be included in resolved services.
        service_names = [s.name for s in resolved.services]
        assert "remote-service" in service_names

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

        from amplifier_ipc_cli.registry import Registry

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()
        registry.register_definition(_AGENT_WITH_URL_BEHAVIOR_YAML)

        with patch(
            "amplifier_ipc_cli.definitions._fetch_url", new_callable=AsyncMock
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
