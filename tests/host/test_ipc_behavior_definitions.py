"""Tests for the IPC-format behavior definition YAML files.

Verifies that each -ipc.yaml definition file:
  - exists on disk
  - is parseable by parse_behavior_definition()
  - has type == "behavior"
  - has the correct local_ref
  - has a non-empty uuid
  - has exactly one service entry with the correct binary name
  - has a source field set (relative or absolute)

Also verifies that scan_location() can discover these files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_ipc.cli.commands.discover import scan_location
from amplifier_ipc.host.definitions import BehaviorDefinition, parse_behavior_definition

# Project root is two levels up from this test file (tests/host/)
PROJECT_ROOT = Path(__file__).parent.parent.parent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFINITIONS = [
    {
        "path": PROJECT_ROOT / "services/amplifier-modes/behaviors/modes-ipc.yaml",
        "local_ref": "modes",
        "service_name": "amplifier-modes-serve",
    },
    {
        "path": PROJECT_ROOT / "services/amplifier-skills/behaviors/skills-ipc.yaml",
        "local_ref": "skills",
        "service_name": "amplifier-skills-serve",
    },
    {
        "path": PROJECT_ROOT
        / "services/amplifier-routing-matrix/behaviors/routing-ipc.yaml",
        "local_ref": "routing",
        "service_name": "amplifier-routing-matrix-serve",
    },
    {
        "path": PROJECT_ROOT
        / "services/amplifier-foundation/behaviors/foundation-ipc.yaml",
        "local_ref": "foundation",
        "service_name": "amplifier-foundation-serve",
    },
    {
        "path": PROJECT_ROOT
        / "services/amplifier-providers/behaviors/providers-ipc.yaml",
        "local_ref": "providers",
        "service_name": "amplifier-providers-serve",
    },
]


# ---------------------------------------------------------------------------
# Parametrised tests — one set per definition file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("defn", DEFINITIONS, ids=[d["local_ref"] for d in DEFINITIONS])
def test_definition_file_exists(defn: dict) -> None:
    """Each -ipc.yaml definition file must exist on disk."""
    assert defn["path"].exists(), f"Missing definition file: {defn['path']}"


@pytest.mark.parametrize("defn", DEFINITIONS, ids=[d["local_ref"] for d in DEFINITIONS])
def test_definition_is_parseable(defn: dict) -> None:
    """parse_behavior_definition() must succeed without raising."""
    yaml_content = defn["path"].read_text(encoding="utf-8")
    result = parse_behavior_definition(yaml_content)
    assert isinstance(result, BehaviorDefinition)


@pytest.mark.parametrize("defn", DEFINITIONS, ids=[d["local_ref"] for d in DEFINITIONS])
def test_definition_type_is_behavior(defn: dict) -> None:
    """The type field must be 'behavior'."""
    yaml_content = defn["path"].read_text(encoding="utf-8")
    result = parse_behavior_definition(yaml_content)
    assert result.type == "behavior", f"Expected type='behavior', got {result.type!r}"


@pytest.mark.parametrize("defn", DEFINITIONS, ids=[d["local_ref"] for d in DEFINITIONS])
def test_definition_local_ref(defn: dict) -> None:
    """The local_ref field must match the expected value."""
    yaml_content = defn["path"].read_text(encoding="utf-8")
    result = parse_behavior_definition(yaml_content)
    assert result.local_ref == defn["local_ref"], (
        f"Expected local_ref={defn['local_ref']!r}, got {result.local_ref!r}"
    )


@pytest.mark.parametrize("defn", DEFINITIONS, ids=[d["local_ref"] for d in DEFINITIONS])
def test_definition_uuid_is_present(defn: dict) -> None:
    """The uuid field must be present and non-empty."""
    yaml_content = defn["path"].read_text(encoding="utf-8")
    result = parse_behavior_definition(yaml_content)
    assert result.uuid, f"uuid is missing or empty in {defn['path'].name}"


@pytest.mark.parametrize("defn", DEFINITIONS, ids=[d["local_ref"] for d in DEFINITIONS])
def test_definition_has_one_service(defn: dict) -> None:
    """The services list must have exactly one entry."""
    yaml_content = defn["path"].read_text(encoding="utf-8")
    result = parse_behavior_definition(yaml_content)
    assert len(result.services) == 1, (
        f"Expected 1 service, got {len(result.services)} in {defn['path'].name}"
    )


@pytest.mark.parametrize("defn", DEFINITIONS, ids=[d["local_ref"] for d in DEFINITIONS])
def test_definition_service_name(defn: dict) -> None:
    """The single service entry must have the correct binary name."""
    yaml_content = defn["path"].read_text(encoding="utf-8")
    result = parse_behavior_definition(yaml_content)
    assert len(result.services) == 1
    assert result.services[0].name == defn["service_name"], (
        f"Expected service name {defn['service_name']!r}, "
        f"got {result.services[0].name!r} in {defn['path'].name}"
    )


@pytest.mark.parametrize("defn", DEFINITIONS, ids=[d["local_ref"] for d in DEFINITIONS])
def test_definition_service_source_is_set(defn: dict) -> None:
    """The service source field must be set (relative or absolute path)."""
    yaml_content = defn["path"].read_text(encoding="utf-8")
    result = parse_behavior_definition(yaml_content)
    assert len(result.services) == 1
    assert result.services[0].source, (
        f"service source is missing in {defn['path'].name}"
    )


# ---------------------------------------------------------------------------
# scan_location discovery test
# ---------------------------------------------------------------------------


def test_scan_location_finds_ipc_definitions() -> None:
    """scan_location() must discover all five -ipc.yaml files in the services/ tree."""
    services_dir = str(PROJECT_ROOT / "services")
    results = scan_location(services_dir)

    # Collect all (type, local_ref) pairs found
    found = {(r["type"], r["local_ref"]) for r in results}

    expected_refs = {"modes", "skills", "routing", "foundation", "providers"}
    found_behavior_refs = {ref for typ, ref in found if typ == "behavior"}

    missing = expected_refs - found_behavior_refs
    assert not missing, (
        f"scan_location() did not find behavior definitions for: {missing}\n"
        f"All discovered: {found}"
    )


def test_scan_location_ipc_definitions_have_paths() -> None:
    """Each discovered IPC definition must have an absolute path pointing to a real file."""
    services_dir = str(PROJECT_ROOT / "services")
    results = scan_location(services_dir)

    ipc_refs = {"modes", "skills", "routing", "foundation", "providers"}
    ipc_results = [
        r for r in results if r.get("local_ref") in ipc_refs and r["type"] == "behavior"
    ]

    for item in ipc_results:
        path = Path(item["path"])
        assert path.is_absolute(), f"Path is not absolute: {path}"
        assert path.exists(), f"Path does not exist: {path}"
        assert path.suffix == ".yaml", f"Expected .yaml suffix: {path}"
