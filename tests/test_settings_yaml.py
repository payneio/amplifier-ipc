"""
Validation tests for .amplifier/settings.yaml local dev overrides.

Verifies:
- File exists with valid YAML
- amplifier_ipc.service_overrides.amplifier-dev contains all 7 services
- Each service has command (list) and working_dir
- modes command starts with 'uv'
"""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
SETTINGS_FILE = PROJECT_ROOT / ".amplifier" / "settings.yaml"

EXPECTED_SERVICES = [
    "foundation",
    "modes",
    "skills",
    "routing",
    "superpowers-methodology",
    "recipes",
    "apply-patch",
]


def load_settings() -> dict:
    assert SETTINGS_FILE.exists(), f"settings.yaml not found at {SETTINGS_FILE}"
    with SETTINGS_FILE.open() as f:
        data = yaml.safe_load(f)
    assert data is not None, "settings.yaml is empty"
    return data


def get_dev_overrides(data: dict) -> dict:
    assert "amplifier_ipc" in data, "Missing top-level 'amplifier_ipc' key"
    assert "service_overrides" in data["amplifier_ipc"], "Missing 'service_overrides'"
    overrides = data["amplifier_ipc"]["service_overrides"]
    assert "amplifier-dev" in overrides, (
        "Missing 'amplifier-dev' under service_overrides"
    )
    return overrides["amplifier-dev"]


def test_settings_yaml_exists():
    """settings.yaml must exist at .amplifier/settings.yaml."""
    assert SETTINGS_FILE.exists(), f"settings.yaml not found at {SETTINGS_FILE}"


def test_settings_yaml_is_valid_yaml():
    """settings.yaml must be parseable YAML."""
    data = load_settings()
    assert isinstance(data, dict), "settings.yaml must be a YAML mapping"


def test_settings_yaml_has_amplifier_ipc_key():
    """Top-level key must be 'amplifier_ipc'."""
    data = load_settings()
    assert "amplifier_ipc" in data


def test_settings_yaml_has_service_overrides():
    """amplifier_ipc must contain service_overrides."""
    data = load_settings()
    assert "service_overrides" in data["amplifier_ipc"]


def test_settings_yaml_has_amplifier_dev():
    """service_overrides must contain amplifier-dev."""
    data = load_settings()
    overrides = data["amplifier_ipc"]["service_overrides"]
    assert "amplifier-dev" in overrides


def test_settings_yaml_has_all_seven_services():
    """amplifier-dev must have all 7 service keys."""
    data = load_settings()
    dev = get_dev_overrides(data)
    for svc in EXPECTED_SERVICES:
        assert svc in dev, f"Missing service '{svc}' in amplifier-dev overrides"


def test_each_service_has_command_and_working_dir():
    """Each service must have 'command' (list) and 'working_dir'."""
    data = load_settings()
    dev = get_dev_overrides(data)
    for svc in EXPECTED_SERVICES:
        entry = dev[svc]
        assert "command" in entry, f"Service '{svc}' missing 'command'"
        assert isinstance(entry["command"], list), (
            f"Service '{svc}' command must be a list"
        )
        assert "working_dir" in entry, f"Service '{svc}' missing 'working_dir'"


def test_modes_command_starts_with_uv():
    """modes.command must start with 'uv'."""
    data = load_settings()
    dev = get_dev_overrides(data)
    modes_cmd = dev["modes"]["command"]
    assert modes_cmd[0] == "uv", (
        f"modes command must start with 'uv', got: {modes_cmd[0]}"
    )


def test_foundation_service_present():
    """foundation service must be present in amplifier-dev."""
    data = load_settings()
    dev = get_dev_overrides(data)
    assert "foundation" in dev


def test_gitignore_has_amplifier_dir():
    """.gitignore must include .amplifier or .amplifier/."""
    gitignore = PROJECT_ROOT / ".gitignore"
    assert gitignore.exists(), ".gitignore not found"
    content = gitignore.read_text()
    assert ".amplifier" in content, ".amplifier not found in .gitignore"
