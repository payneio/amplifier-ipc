"""
Validation tests for rewritten foundation behavior YAML files.
Each file must have: behavior.ref, behavior.uuid, NO service block.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# Resolve paths relative to the project root (parent of the tests/ directory)
PROJECT_ROOT = Path(__file__).parent.parent
BEHAVIORS_DIR = PROJECT_ROOT / "services" / "amplifier-foundation" / "behaviors"

FILES = {
    "sessions": BEHAVIORS_DIR / "sessions.yaml",
    "shadow-amplifier": BEHAVIORS_DIR / "shadow-amplifier.yaml",
    "status-context": BEHAVIORS_DIR / "status-context.yaml",
    "streaming-ui": BEHAVIORS_DIR / "streaming-ui.yaml",
    "tasks": BEHAVIORS_DIR / "tasks.yaml",
    "todo-reminder": BEHAVIORS_DIR / "todo-reminder.yaml",
}

EXPECTED: dict[str, dict] = {
    "sessions": {
        "ref": "sessions",
        "hooks": True,
        "config_key": "session-naming-hook",
        "config_check": ("trigger", "first_response"),
    },
    "shadow-amplifier": {
        "ref": "shadow-amplifier",
        "context": True,
    },
    "status-context": {
        "ref": "status-context",
        "hooks": True,
        "config_key": "status-context-hook",
        "config_check": ("include_git_status", True),
    },
    "streaming-ui": {
        "ref": "streaming-ui",
        "hooks": True,
        "config_key": "streaming-ui-hook",
        "config_check": ("show_tool_calls", True),
    },
    "tasks": {
        "ref": "tasks",
        "tools": True,
        "context": True,
        "config_key": "task-tool",
        "config_check": ("exclude_tools", ["tool-delegate"]),
    },
    "todo-reminder": {
        "ref": "todo-reminder",
        "tools": True,
        "hooks": True,
        "config_key": "todo-reminder-hook",
        "config_key2": "todo-display-hook",
        "config_check": ("inject_role", "user"),
    },
}


def load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def check_file(name: str, path: Path, expected: dict) -> list[str]:
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

    # Check uuid exists and is non-empty
    if not b.get("uuid"):
        errors.append("uuid is missing or empty")

    # Check version == 1
    if b.get("version") != 1:
        errors.append(f"version mismatch: expected 1, got {b.get('version')}")

    # CRITICAL: service must NOT be present
    if "service" in b:
        errors.append("'service' block must NOT be present in foundation behavior")

    # Check behaviors is a list
    if not isinstance(b.get("behaviors"), list):
        errors.append(f"'behaviors' should be a list, got {type(b.get('behaviors'))}")

    # Check boolean flags listed in EXPECTED are set to true; unlisted flags are not asserted
    for flag in ("tools", "hooks", "context"):
        if flag in expected:
            if b.get(flag) is not True:
                errors.append(f"'{flag}' flag should be true, got {b.get(flag)}")
        else:
            if b.get(flag) is True:
                errors.append(f"'{flag}' flag is present but not expected for '{name}'")

    # Check specific config keys
    if "config_key" in expected:
        config = b.get("config", {})
        key = expected["config_key"]
        if key not in config:
            errors.append(f"config.{key} is missing")
        elif "config_check" in expected:
            field, val = expected["config_check"]
            if config[key].get(field) != val:
                errors.append(
                    f"config.{key}.{field} mismatch: expected {val!r}, got {config[key].get(field)!r}"
                )

    # Check second config key for todo-reminder
    if "config_key2" in expected:
        config = b.get("config", {})
        key2 = expected["config_key2"]
        if key2 not in config:
            errors.append(f"config.{key2} is missing")

    return errors


def test_sessions() -> None:
    errors = check_file("sessions", FILES["sessions"], EXPECTED["sessions"])
    assert not errors, f"sessions.yaml errors: {errors}"


def test_shadow_amplifier() -> None:
    errors = check_file(
        "shadow-amplifier", FILES["shadow-amplifier"], EXPECTED["shadow-amplifier"]
    )
    assert not errors, f"shadow-amplifier.yaml errors: {errors}"


def test_status_context() -> None:
    errors = check_file(
        "status-context", FILES["status-context"], EXPECTED["status-context"]
    )
    assert not errors, f"status-context.yaml errors: {errors}"


def test_streaming_ui() -> None:
    errors = check_file("streaming-ui", FILES["streaming-ui"], EXPECTED["streaming-ui"])
    assert not errors, f"streaming-ui.yaml errors: {errors}"


def test_tasks() -> None:
    errors = check_file("tasks", FILES["tasks"], EXPECTED["tasks"])
    assert not errors, f"tasks.yaml errors: {errors}"


def test_todo_reminder() -> None:
    errors = check_file(
        "todo-reminder", FILES["todo-reminder"], EXPECTED["todo-reminder"]
    )
    assert not errors, f"todo-reminder.yaml errors: {errors}"
