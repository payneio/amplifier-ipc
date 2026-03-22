"""Tests for the IPC-format agent definition YAML file.

Verifies that services/amplifier-foundation/agents/amplifier-dev.yaml:
  - exists on disk
  - is parseable by parse_agent_definition()
  - has all required fields in spec-compliant format
  - is discoverable by scan_location()
  - resolves correctly (integration) when behaviors are pre-registered
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import yaml

from amplifier_ipc.cli.commands.discover import scan_location
from amplifier_ipc.host.definition_registry import Registry
from amplifier_ipc.host.definitions import (
    AgentDefinition,
    ResolvedAgent,
    parse_agent_definition,
    resolve_agent,
)

# Project root is two levels up from this test file (tests/host/)
PROJECT_ROOT = Path(__file__).parent.parent.parent

AGENT_DEF_PATH = (
    PROJECT_ROOT / "services/amplifier-foundation/agents/amplifier-dev.yaml"
)

# ---------------------------------------------------------------------------
# File-level helpers
# ---------------------------------------------------------------------------


def _load_raw_yaml() -> dict:
    """Load the raw YAML from the agent definition file."""
    return yaml.safe_load(AGENT_DEF_PATH.read_text(encoding="utf-8"))


def _parse() -> AgentDefinition:
    """Parse the agent definition file."""
    return parse_agent_definition(
        AGENT_DEF_PATH.read_text(encoding="utf-8"), path=AGENT_DEF_PATH
    )


# ---------------------------------------------------------------------------
# Basic file existence and parseability
# ---------------------------------------------------------------------------


def test_agent_definition_file_exists() -> None:
    """The amplifier-dev.yaml must exist at the expected path."""
    assert AGENT_DEF_PATH.exists(), f"Missing agent definition: {AGENT_DEF_PATH}"


def test_agent_definition_is_parseable() -> None:
    """parse_agent_definition() must succeed without raising."""
    result = _parse()
    assert isinstance(result, AgentDefinition)


# ---------------------------------------------------------------------------
# Required field values
# ---------------------------------------------------------------------------


def test_agent_type_is_agent() -> None:
    """The type field must be 'agent'."""
    result = _parse()
    assert result.type == "agent", f"Expected type='agent', got {result.type!r}"


def test_agent_local_ref() -> None:
    """The local_ref field must be 'amplifier-dev'."""
    result = _parse()
    assert result.local_ref == "amplifier-dev", (
        f"Expected local_ref='amplifier-dev', got {result.local_ref!r}"
    )


def test_agent_uuid_present_and_valid() -> None:
    """The uuid field must be present, non-empty, and a valid UUID4 string."""
    result = _parse()
    assert result.uuid, "uuid is missing or empty"
    # Must be parseable as a UUID
    parsed_uuid = uuid.UUID(result.uuid)
    assert parsed_uuid.version == 4, (
        f"Expected UUID version 4, got {parsed_uuid.version}"
    )


def test_agent_orchestrator() -> None:
    """The orchestrator field must be 'streaming'."""
    result = _parse()
    assert result.orchestrator == "streaming", (
        f"Expected orchestrator='streaming', got {result.orchestrator!r}"
    )


def test_agent_context_manager() -> None:
    """The context_manager field must be 'simple'."""
    result = _parse()
    assert result.context_manager == "simple", (
        f"Expected context_manager='simple', got {result.context_manager!r}"
    )


def test_agent_provider() -> None:
    """The provider field must be 'anthropic'."""
    result = _parse()
    assert result.provider == "anthropic", (
        f"Expected provider='anthropic', got {result.provider!r}"
    )


# ---------------------------------------------------------------------------
# Boolean flags — must be `true` in the raw YAML
# (parsed as [] by _to_str_list, but the raw YAML values are the spec signal)
# ---------------------------------------------------------------------------


def test_agent_tools_flag_is_true_in_yaml() -> None:
    """The raw YAML must have `tools: true`."""
    raw = _load_raw_yaml()
    assert raw.get("tools") is True, f"Expected tools: true, got {raw.get('tools')!r}"


def test_agent_hooks_flag_is_true_in_yaml() -> None:
    """The raw YAML must have `hooks: true`."""
    raw = _load_raw_yaml()
    assert raw.get("hooks") is True, f"Expected hooks: true, got {raw.get('hooks')!r}"


def test_agent_agents_flag_is_true_in_yaml() -> None:
    """The raw YAML must have `agents: true`."""
    raw = _load_raw_yaml()
    assert raw.get("agents") is True, (
        f"Expected agents: true, got {raw.get('agents')!r}"
    )


def test_agent_context_flag_is_true_in_yaml() -> None:
    """The raw YAML must have `context: true`."""
    raw = _load_raw_yaml()
    assert raw.get("context") is True, (
        f"Expected context: true, got {raw.get('context')!r}"
    )


# ---------------------------------------------------------------------------
# Behaviors list
# ---------------------------------------------------------------------------


def test_agent_behaviors_has_three_entries() -> None:
    """The behaviors list must have exactly 3 entries."""
    result = _parse()
    assert len(result.behaviors) == 3, (
        f"Expected 3 behaviors, got {len(result.behaviors)}: {result.behaviors}"
    )


def test_agent_behaviors_contains_modes() -> None:
    """The behaviors list must include 'modes'."""
    result = _parse()
    assert "modes" in result.behaviors, (
        f"'modes' not found in behaviors: {result.behaviors}"
    )


def test_agent_behaviors_contains_skills() -> None:
    """The behaviors list must include 'skills'."""
    result = _parse()
    assert "skills" in result.behaviors, (
        f"'skills' not found in behaviors: {result.behaviors}"
    )


def test_agent_behaviors_contains_routing() -> None:
    """The behaviors list must include 'routing'."""
    result = _parse()
    assert "routing" in result.behaviors, (
        f"'routing' not found in behaviors: {result.behaviors}"
    )


# ---------------------------------------------------------------------------
# Services list
# ---------------------------------------------------------------------------


def test_agent_services_has_two_entries() -> None:
    """The services list must have exactly 2 entries."""
    result = _parse()
    assert len(result.services) == 2, (
        f"Expected 2 services, got {len(result.services)}: {[s.name for s in result.services]}"
    )


def test_agent_services_includes_foundation() -> None:
    """The services list must include 'amplifier-foundation-serve'."""
    result = _parse()
    names = [s.name for s in result.services]
    assert "amplifier-foundation-serve" in names, (
        f"'amplifier-foundation-serve' not in services: {names}"
    )


def test_agent_services_includes_providers() -> None:
    """The services list must include 'amplifier-providers-serve'."""
    result = _parse()
    names = [s.name for s in result.services]
    assert "amplifier-providers-serve" in names, (
        f"'amplifier-providers-serve' not in services: {names}"
    )


def test_agent_service_sources_are_set() -> None:
    """All service entries must have a non-empty source field."""
    result = _parse()
    for svc in result.services:
        assert svc.source, f"Service '{svc.name}' has no source"


# ---------------------------------------------------------------------------
# Discoverability
# ---------------------------------------------------------------------------


def test_scan_location_finds_amplifier_dev_agent() -> None:
    """scan_location() must discover amplifier-dev as an agent definition."""
    services_dir = str(PROJECT_ROOT / "services")
    results = scan_location(services_dir)

    found = {(r["type"], r["local_ref"]) for r in results}
    assert ("agent", "amplifier-dev") in found, (
        f"('agent', 'amplifier-dev') not found in scan results.\n"
        f"All discovered: {found}"
    )


def test_scan_location_agent_has_valid_path() -> None:
    """The discovered amplifier-dev agent must have an absolute path to a real file."""
    services_dir = str(PROJECT_ROOT / "services")
    results = scan_location(services_dir)

    agent_results = [
        r for r in results if r["type"] == "agent" and r["local_ref"] == "amplifier-dev"
    ]
    assert len(agent_results) == 1, (
        f"Expected exactly 1 amplifier-dev agent result, got {len(agent_results)}"
    )
    path = Path(agent_results[0]["path"])
    assert path.is_absolute(), f"Path is not absolute: {path}"
    assert path.exists(), f"Path does not exist: {path}"
    assert path.suffix == ".yaml", f"Expected .yaml suffix: {path}"


# ---------------------------------------------------------------------------
# Integration: resolve_agent() collects all 5 services
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_agent_collects_five_services(tmp_path: Path) -> None:
    """resolve_agent() must return a ResolvedAgent with 5 distinct services.

    Registers all 5 behavior definitions and the agent definition, then
    resolves 'amplifier-dev' and checks that the full service set is collected:
      - amplifier-foundation-serve   (from agent's services: block)
      - amplifier-providers-serve    (from agent's services: block)
      - amplifier-modes-serve        (from modes behavior)
      - amplifier-skills-serve       (from skills behavior)
      - amplifier-routing-matrix-serve (from routing behavior)
    """
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    # Register all 5 behavior definitions
    behavior_paths = [
        PROJECT_ROOT / "services/amplifier-modes/behaviors/modes-ipc.yaml",
        PROJECT_ROOT / "services/amplifier-skills/behaviors/skills-ipc.yaml",
        PROJECT_ROOT / "services/amplifier-routing-matrix/behaviors/routing-ipc.yaml",
        PROJECT_ROOT / "services/amplifier-foundation/behaviors/foundation-ipc.yaml",
        PROJECT_ROOT / "services/amplifier-providers/behaviors/providers-ipc.yaml",
    ]
    for bp in behavior_paths:
        registry.register_definition(bp.read_text(encoding="utf-8"))

    # Register the agent definition
    registry.register_definition(AGENT_DEF_PATH.read_text(encoding="utf-8"))

    # Resolve the agent
    resolved = await resolve_agent(registry, "amplifier-dev")

    assert isinstance(resolved, ResolvedAgent)

    service_names = {s.name for s in resolved.services}
    expected = {
        "amplifier-foundation-serve",
        "amplifier-providers-serve",
        "amplifier-modes-serve",
        "amplifier-skills-serve",
        "amplifier-routing-matrix-serve",
    }
    missing = expected - service_names
    assert not missing, (
        f"Missing services in resolved agent: {missing}\nGot: {service_names}"
    )
    assert len(resolved.services) == 5, (
        f"Expected 5 services, got {len(resolved.services)}: {service_names}"
    )


@pytest.mark.asyncio
async def test_resolve_agent_orchestrator_and_provider(tmp_path: Path) -> None:
    """resolve_agent() must carry through orchestrator, context_manager, and provider."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    # Register only the 3 behaviors the agent references by local_ref
    for local_ref, rel_path in [
        ("modes", "services/amplifier-modes/behaviors/modes-ipc.yaml"),
        ("skills", "services/amplifier-skills/behaviors/skills-ipc.yaml"),
        ("routing", "services/amplifier-routing-matrix/behaviors/routing-ipc.yaml"),
    ]:
        path = PROJECT_ROOT / rel_path
        registry.register_definition(path.read_text(encoding="utf-8"))

    registry.register_definition(AGENT_DEF_PATH.read_text(encoding="utf-8"))

    resolved = await resolve_agent(registry, "amplifier-dev")

    assert resolved.orchestrator == "streaming"
    assert resolved.context_manager == "simple"
    assert resolved.provider == "anthropic"
