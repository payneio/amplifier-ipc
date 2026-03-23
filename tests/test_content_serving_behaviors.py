"""
Validation tests for rewritten content-serving behavior YAML files.
Each file must have: behavior.ref, behavior.uuid, behavior.service block
with stack/source/command. No agents: blocks, context: true, behaviors: [].
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

# Resolve paths relative to the project root (parent of the tests/ directory)
PROJECT_ROOT = Path(__file__).parent.parent

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

IPC_BASE = "git+https://github.com/payneio/amplifier-ipc@main#subdirectory=services/"

FILES = {
    "amplifier-expert": PROJECT_ROOT
    / "services/amplifier-amplifier/behaviors/amplifier-expert.yaml",
    "amplifier-dev-hygiene": PROJECT_ROOT
    / "services/amplifier-amplifier/behaviors/amplifier-dev.yaml",
    "core-expert": PROJECT_ROOT / "services/amplifier-core/behaviors/core-expert.yaml",
    "design-intelligence": PROJECT_ROOT
    / "services/amplifier-design-intelligence/behaviors/design-intelligence.yaml",
    "browser-tester": PROJECT_ROOT
    / "services/amplifier-browser-tester/behaviors/browser-tester.yaml",
}

EXPECTED: dict[str, dict] = {
    "amplifier-expert": {
        "ref": "amplifier-expert",
        "service_command": "amplifier-amplifier-serve",
        "service_source_subdir": "amplifier-amplifier",
    },
    "amplifier-dev-hygiene": {
        "ref": "amplifier-dev-hygiene",
        "service_command": "amplifier-amplifier-serve",
        "service_source_subdir": "amplifier-amplifier",
    },
    "core-expert": {
        "ref": "core-expert",
        "service_command": "amplifier-core-serve",
        "service_source_subdir": "amplifier-core",
    },
    "design-intelligence": {
        "ref": "design-intelligence",
        "service_command": "amplifier-design-intelligence-serve",
        "service_source_subdir": "amplifier-design-intelligence",
    },
    "browser-tester": {
        "ref": "browser-tester",
        "service_command": "amplifier-browser-tester-serve",
        "service_source_subdir": "amplifier-browser-tester",
    },
}


def load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def check_content_serving_file(name: str, path: Path, expected: dict) -> list[str]:
    errors: list[str] = []
    try:
        data = load_yaml(path)
    except Exception as e:
        return [f"Failed to load YAML: {e}"]

    # Check top-level key
    if "behavior" not in data:
        errors.append("Missing top-level 'behavior' key")
        return errors

    b = data["behavior"]

    # Check ref
    if b.get("ref") != expected["ref"]:
        errors.append(
            f"ref mismatch: expected '{expected['ref']}', got '{b.get('ref')}'"
        )

    # Check uuid exists and is a valid UUID
    uuid_val = b.get("uuid")
    if not uuid_val:
        errors.append("uuid is missing or empty")
    elif not UUID_RE.match(str(uuid_val)):
        errors.append(f"uuid is not a valid UUID format: '{uuid_val}'")

    # Check version == 1
    if b.get("version") != 1:
        errors.append(f"version mismatch: expected 1, got {b.get('version')}")

    # Check context is true
    if b.get("context") is not True:
        errors.append(f"'context' should be true, got {b.get('context')!r}")

    # Check behaviors is an empty list
    behaviors = b.get("behaviors")
    if not isinstance(behaviors, list):
        errors.append(f"'behaviors' should be a list, got {type(behaviors)}")
    elif behaviors:
        errors.append(f"'behaviors' should be empty, got {behaviors!r}")

    # Check agents must NOT be present (replaced by service block)
    if "agents" in b:
        errors.append("'agents' block must NOT be present in content-serving behavior")

    # Check service block is present
    if "service" not in b:
        errors.append("'service' block is required for content-serving behavior")
        return errors

    svc = b["service"]

    # Check stack == "uv"
    if svc.get("stack") != "uv":
        errors.append(
            f"service.stack mismatch: expected 'uv', got '{svc.get('stack')}'"
        )

    # Check source contains correct subdirectory
    expected_source = IPC_BASE + expected["service_source_subdir"]
    if svc.get("source") != expected_source:
        errors.append(
            f"service.source mismatch: expected '{expected_source}', got '{svc.get('source')}'"
        )

    # Check command
    if svc.get("command") != expected["service_command"]:
        errors.append(
            f"service.command mismatch: expected '{expected['service_command']}', "
            f"got '{svc.get('command')}'"
        )

    return errors


def test_amplifier_expert() -> None:
    errors = check_content_serving_file(
        "amplifier-expert", FILES["amplifier-expert"], EXPECTED["amplifier-expert"]
    )
    assert not errors, f"amplifier-expert.yaml errors: {errors}"


def test_amplifier_dev_hygiene() -> None:
    errors = check_content_serving_file(
        "amplifier-dev-hygiene",
        FILES["amplifier-dev-hygiene"],
        EXPECTED["amplifier-dev-hygiene"],
    )
    assert not errors, f"amplifier-dev.yaml errors: {errors}"


def test_core_expert() -> None:
    errors = check_content_serving_file(
        "core-expert", FILES["core-expert"], EXPECTED["core-expert"]
    )
    assert not errors, f"core-expert.yaml errors: {errors}"


def test_design_intelligence() -> None:
    errors = check_content_serving_file(
        "design-intelligence",
        FILES["design-intelligence"],
        EXPECTED["design-intelligence"],
    )
    assert not errors, f"design-intelligence.yaml errors: {errors}"


def test_browser_tester() -> None:
    errors = check_content_serving_file(
        "browser-tester", FILES["browser-tester"], EXPECTED["browser-tester"]
    )
    assert not errors, f"browser-tester.yaml errors: {errors}"
