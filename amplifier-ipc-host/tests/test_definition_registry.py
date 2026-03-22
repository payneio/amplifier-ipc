"""Tests for the definition registry (Registry class managing $AMPLIFIER_HOME layout)."""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_ipc_host.definition_registry import Registry


def test_ensure_home_creates_structure(tmp_path: Path) -> None:
    """ensure_home() creates the expected directory structure and alias files."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    home = registry.home
    assert home.is_dir(), "home directory should be created"
    assert (home / "definitions").is_dir(), (
        "definitions/ subdirectory should be created"
    )
    assert (home / "environments").is_dir(), (
        "environments/ subdirectory should be created"
    )
    assert (home / "agents.yaml").is_file(), "agents.yaml should be created"
    assert (home / "behaviors.yaml").is_file(), "behaviors.yaml should be created"

    # Alias files should be initialized as empty mappings
    import yaml

    agents_data = yaml.safe_load((home / "agents.yaml").read_text())
    behaviors_data = yaml.safe_load((home / "behaviors.yaml").read_text())
    assert agents_data == {} or agents_data is None
    assert behaviors_data == {} or behaviors_data is None


def test_register_agent_definition(tmp_path: Path) -> None:
    """register_definition() registers an agent, writes a definition file, and updates agents.yaml."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = (
        "type: agent\n"
        "local_ref: my-agent\n"
        "uuid: 12345678-abcd-ef00-0000-000000000000\n"
        "name: My Agent\n"
    )

    definition_id = registry.register_definition(yaml_content)

    # Definition ID follows the pattern <type>_<local_ref>_<uuid_first_8>
    assert definition_id == "agent_my-agent_12345678"

    # Definition file should exist
    def_file = registry.home / "definitions" / f"{definition_id}.yaml"
    assert def_file.is_file(), "definition file should be created"

    # agents.yaml should map local_ref → definition_id
    import yaml

    alias_data = yaml.safe_load((registry.home / "agents.yaml").read_text())
    assert alias_data["my-agent"] == definition_id


def test_register_behavior_definition(tmp_path: Path) -> None:
    """register_definition() registers a behavior and updates behaviors.yaml."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = (
        "type: behavior\n"
        "local_ref: my-behavior\n"
        "uuid: abcdefab-0000-0000-0000-000000000000\n"
        "name: My Behavior\n"
    )

    definition_id = registry.register_definition(yaml_content)

    assert definition_id == "behavior_my-behavior_abcdefab"

    # behaviors.yaml should be updated; agents.yaml should remain empty
    import yaml

    behaviors_data = yaml.safe_load((registry.home / "behaviors.yaml").read_text())
    agents_data = yaml.safe_load((registry.home / "agents.yaml").read_text())

    assert behaviors_data["my-behavior"] == definition_id
    assert "my-behavior" not in (agents_data or {})


def test_resolve_agent_returns_path(tmp_path: Path) -> None:
    """resolve_agent() returns the path to a registered agent's definition file."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = (
        "type: agent\n"
        "local_ref: cool-agent\n"
        "uuid: deadbeef-0000-0000-0000-000000000000\n"
        "name: Cool Agent\n"
    )
    definition_id = registry.register_definition(yaml_content)

    result_path = registry.resolve_agent("cool-agent")

    expected_path = registry.home / "definitions" / f"{definition_id}.yaml"
    assert result_path == expected_path
    assert result_path.is_file()


def test_resolve_agent_unknown_raises(tmp_path: Path) -> None:
    """resolve_agent() raises FileNotFoundError for an unregistered agent name."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    with pytest.raises(FileNotFoundError, match="nonexistent-agent"):
        registry.resolve_agent("nonexistent-agent")
