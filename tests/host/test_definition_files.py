"""Comprehensive parametric test suite for validating every YAML definition file in services/."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

from amplifier_ipc.cli.commands.discover import scan_location
from amplifier_ipc.host.definitions import (
    AgentDefinition,
    BehaviorDefinition,
    parse_agent_definition,
    parse_behavior_definition,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVICES_DIR = Path(__file__).parent.parent.parent / "services"

# Behaviors that had config in old format and must have a config: block
BEHAVIORS_WITH_CONFIG = {
    "agents",
    "tasks",
    "todo-reminder",
    "streaming-ui",
    "status-context",
    "sessions",
    "redaction",
    "progress-monitor",
    "logging",
    "routing",
    "skills",
    "skills-tool",
    "apply-patch",
    "recipes",
    "superpowers-methodology",
}

EXPECTED_AGENT_REFS = {
    "amplifier-dev",
    "foundation",
    "minimal",
    "with-anthropic",
    "with-openai",
}
EXPECTED_BEHAVIOR_REFS = {"modes", "skills", "routing", "recipes", "apply-patch"}


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def _collect_definitions() -> list[dict[str, Any]]:
    """Scan services/ for agent/behavior YAML definitions, augmented with parsed YAML.

    Filters out .venv (installed package copies) and src/ (duplicate source mirrors)
    to avoid false positives and duplicate parametrize IDs.
    """
    raw_results = scan_location(str(SERVICES_DIR))
    results: list[dict[str, Any]] = []
    for entry in raw_results:
        path = entry["path"]
        # Skip entries from .venv directories (installed/vendored packages)
        if ".venv" in Path(path).parts:
            continue
        # Skip entries from src/ directories (duplicates of top-level definitions);
        # check parts[:-1] (directories only) so a file literally named "src" isn't excluded
        if "src" in Path(path).parts[:-1]:
            continue
        # Augment with parsed YAML data
        try:
            parsed = yaml.safe_load(entry["raw_content"])
        except yaml.YAMLError:
            parsed = None
        augmented = dict(entry)
        augmented["parsed"] = parsed
        results.append(augmented)
    return results


DEFINITIONS = _collect_definitions()
AGENT_DEFS = [d for d in DEFINITIONS if d["type"] == "agent"]
BEHAVIOR_DEFS = [d for d in DEFINITIONS if d["type"] == "behavior"]
BEHAVIOR_DEFS_WITH_CONFIG = [
    d for d in BEHAVIOR_DEFS if d["ref"] in BEHAVIORS_WITH_CONFIG
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _def_id(d: dict[str, Any]) -> str:
    """Return a short ID for parametrize labels."""
    return d.get("ref") or Path(d["path"]).stem


def _inner(defn: dict[str, Any]) -> dict[str, Any]:
    """Extract the type-keyed inner block from a parsed definition dict."""
    parsed = defn["parsed"]
    return parsed.get(defn["type"], {}) if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Tests: Every definition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("defn", DEFINITIONS, ids=_def_id)
def test_definition_has_ref(defn: dict[str, Any]) -> None:
    """Every definition must have a non-empty 'ref'."""
    assert defn["ref"], f"Missing or empty ref in {defn['path']}"


@pytest.mark.parametrize("defn", DEFINITIONS, ids=_def_id)
def test_definition_has_valid_uuid(defn: dict[str, Any]) -> None:
    """Every definition must have a valid UUID v4."""
    inner = _inner(defn)
    uuid_str = inner.get("uuid")
    assert uuid_str, f"Missing uuid in {defn['path']}"
    parsed_uuid = None
    try:
        parsed_uuid = uuid.UUID(str(uuid_str))
    except ValueError:
        pass
    assert parsed_uuid is not None, (
        f"Invalid UUID format '{uuid_str}' in {defn['path']}"
    )
    assert parsed_uuid.version == 4, f"UUID is not v4 in {defn['path']}: {uuid_str}"


@pytest.mark.parametrize("defn", DEFINITIONS, ids=_def_id)
def test_definition_has_no_old_format_fields(defn: dict[str, Any]) -> None:
    """No old fields: type, local_ref, services, installer, or name in service block."""
    inner = _inner(defn)

    old_inner_fields = ["type", "local_ref", "services", "installer"]
    for field_name in old_inner_fields:
        assert field_name not in inner, (
            f"Old field '{field_name}' found in definition at {defn['path']}"
        )

    # Check the service block doesn't contain the old 'name' field
    service = inner.get("service", {})
    if isinstance(service, dict):
        assert "name" not in service, (
            f"Old 'name' field found in service block of {defn['path']}"
        )


@pytest.mark.parametrize("defn", DEFINITIONS, ids=_def_id)
def test_definition_service_block_is_valid(defn: dict[str, Any]) -> None:
    """If service: is present, it must have stack, source, and command."""
    inner = _inner(defn)
    service = inner.get("service")

    if service is None:
        return  # No service block — passes vacuously

    assert isinstance(service, dict), f"service: must be a dict in {defn['path']}"
    for required_key in ("stack", "source", "command"):
        assert required_key in service, (
            f"service: block missing '{required_key}' in {defn['path']}"
        )


@pytest.mark.parametrize("defn", DEFINITIONS, ids=_def_id)
def test_definition_behaviors_format(defn: dict[str, Any]) -> None:
    """If behaviors: is present, all entries must be single-key {{alias: url}} dicts."""
    inner = _inner(defn)
    behaviors = inner.get("behaviors")

    if not behaviors:
        return  # No behaviors or empty list — passes vacuously

    assert isinstance(behaviors, list), f"behaviors: must be a list in {defn['path']}"
    for entry in behaviors:
        assert isinstance(entry, dict), (
            f"behaviors: entry must be a dict in {defn['path']}: {entry!r}"
        )
        assert len(entry) == 1, (
            f"behaviors: entry must have exactly one key in {defn['path']}: {entry!r}"
        )


# ---------------------------------------------------------------------------
# Tests: Agent definitions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("defn", AGENT_DEFS, ids=_def_id)
def test_agent_definition_parseable(defn: dict[str, Any]) -> None:
    """Every agent definition must be parseable by parse_agent_definition()."""
    result = parse_agent_definition(defn["raw_content"])
    assert isinstance(result, AgentDefinition), (
        f"parse_agent_definition() did not return AgentDefinition for {defn['path']}"
    )


@pytest.mark.parametrize("defn", AGENT_DEFS, ids=_def_id)
def test_agent_has_orchestrator(defn: dict[str, Any]) -> None:
    """Agent definitions should have an orchestrator field."""
    result = parse_agent_definition(defn["raw_content"])
    assert result.orchestrator, (
        f"Agent '{defn['ref']}' in {defn['path']} is missing orchestrator"
    )


# ---------------------------------------------------------------------------
# Tests: Behavior definitions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("defn", BEHAVIOR_DEFS, ids=_def_id)
def test_behavior_definition_parseable(defn: dict[str, Any]) -> None:
    """Every behavior definition must be parseable by parse_behavior_definition()."""
    result = parse_behavior_definition(defn["raw_content"])
    assert isinstance(result, BehaviorDefinition), (
        f"parse_behavior_definition() did not return BehaviorDefinition for {defn['path']}"
    )


@pytest.mark.parametrize("defn", BEHAVIOR_DEFS_WITH_CONFIG, ids=_def_id)
def test_behavior_with_config_has_config_block(defn: dict[str, Any]) -> None:
    """Behaviors that require config must have a non-empty config: block."""
    inner = _inner(defn)
    assert "config" in inner, (
        f"Behavior '{defn['ref']}' in {defn['path']} is missing required config: block"
    )
    assert isinstance(inner["config"], dict), (
        f"config: block in {defn['path']} must be a dict"
    )
    assert inner["config"], f"config: block in {defn['path']} must not be empty"


@pytest.mark.parametrize("defn", BEHAVIOR_DEFS_WITH_CONFIG, ids=_def_id)
def test_config_keys_are_component_names(defn: dict[str, Any]) -> None:
    """Config block keys must be bare component names (no ref: prefix or colon)."""
    inner = _inner(defn)
    config = inner.get("config", {})

    if not isinstance(config, dict) or not config:
        return  # No config to validate

    for key in config:
        assert not str(key).startswith("ref:"), (
            f"Config key '{key}' in {defn['path']} uses old 'ref:' prefix format"
        )
        assert ":" not in str(key), (
            f"Config key '{key}' in {defn['path']} contains a colon — should be bare component name"
        )


# ---------------------------------------------------------------------------
# Tests: Discovery completeness
# ---------------------------------------------------------------------------


def test_scan_finds_all_agent_definitions() -> None:
    """Scan must find: amplifier-dev, foundation, minimal, with-anthropic, with-openai."""
    agent_refs = {d["ref"] for d in AGENT_DEFS}
    for expected_ref in sorted(EXPECTED_AGENT_REFS):
        assert expected_ref in agent_refs, (
            f"Expected agent '{expected_ref}' not found in scan results. "
            f"Found refs: {sorted(agent_refs)}"
        )


def test_scan_finds_expected_behavior_definitions() -> None:
    """Scan must find: modes, skills, routing, recipes, apply-patch."""
    behavior_refs = {d["ref"] for d in BEHAVIOR_DEFS}
    for expected_ref in sorted(EXPECTED_BEHAVIOR_REFS):
        assert expected_ref in behavior_refs, (
            f"Expected behavior '{expected_ref}' not found in scan results. "
            f"Found refs: {sorted(behavior_refs)}"
        )
