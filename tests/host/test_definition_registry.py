"""Tests for the definition registry (Registry class managing $AMPLIFIER_HOME layout)."""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_ipc.host.definition_registry import Registry


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


# ---------------------------------------------------------------------------
# Tests for unregister_definition()
# ---------------------------------------------------------------------------


def test_unregister_definition_removes_definition_file(tmp_path: Path) -> None:
    """unregister_definition() deletes the definition file from definitions/."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = (
        "type: agent\n"
        "local_ref: my-agent\n"
        "uuid: 12345678-abcd-ef00-0000-000000000000\n"
        "name: My Agent\n"
    )
    definition_id = registry.register_definition(yaml_content)

    def_file = registry.home / "definitions" / f"{definition_id}.yaml"
    assert def_file.exists(), "definition file must exist before unregistering"

    registry.unregister_definition("my-agent", kind="agent")

    assert not def_file.exists(), "definition file should be deleted after unregister"


def test_unregister_definition_removes_alias_entries(tmp_path: Path) -> None:
    """unregister_definition() removes all alias entries that mapped to the definition."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = (
        "type: agent\n"
        "local_ref: my-agent\n"
        "uuid: 12345678-abcd-ef00-0000-000000000000\n"
        "name: My Agent\n"
    )
    registry.register_definition(yaml_content)

    import yaml

    # local_ref alias should exist before unregister
    alias_data = yaml.safe_load((registry.home / "agents.yaml").read_text()) or {}
    assert "my-agent" in alias_data

    registry.unregister_definition("my-agent", kind="agent")

    alias_data = yaml.safe_load((registry.home / "agents.yaml").read_text()) or {}
    assert "my-agent" not in alias_data, "local_ref alias must be removed"


def test_unregister_definition_removes_source_url_alias(tmp_path: Path) -> None:
    """unregister_definition() also removes the source_url alias when registered via URL."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = (
        "type: agent\n"
        "local_ref: url-agent\n"
        "uuid: abcdef12-0000-0000-0000-000000000000\n"
        "name: URL Agent\n"
    )
    source_url = "https://example.com/url-agent.yaml"
    registry.register_definition(yaml_content, source_url=source_url)

    import yaml

    alias_data = yaml.safe_load((registry.home / "agents.yaml").read_text()) or {}
    assert source_url in alias_data, "source_url alias must exist after register"

    registry.unregister_definition("url-agent", kind="agent")

    alias_data = yaml.safe_load((registry.home / "agents.yaml").read_text()) or {}
    assert "url-agent" not in alias_data, "local_ref alias must be removed"
    assert source_url not in alias_data, "source_url alias must also be removed"


def test_unregister_definition_returns_definition_id(tmp_path: Path) -> None:
    """unregister_definition() returns the definition_id that was removed."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = (
        "type: agent\n"
        "local_ref: ret-agent\n"
        "uuid: 11111111-0000-0000-0000-000000000000\n"
        "name: Ret Agent\n"
    )
    expected_id = registry.register_definition(yaml_content)

    returned_id = registry.unregister_definition("ret-agent", kind="agent")

    assert returned_id == expected_id


def test_unregister_definition_unknown_raises(tmp_path: Path) -> None:
    """unregister_definition() raises FileNotFoundError for an unknown name."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    with pytest.raises(FileNotFoundError, match="ghost-agent"):
        registry.unregister_definition("ghost-agent", kind="agent")


def test_unregister_behavior_definition(tmp_path: Path) -> None:
    """unregister_definition() works for behaviors (uses behaviors.yaml)."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = (
        "type: behavior\n"
        "local_ref: my-behavior\n"
        "uuid: aaaabbbb-0000-0000-0000-000000000000\n"
        "name: My Behavior\n"
    )
    definition_id = registry.register_definition(yaml_content)

    returned_id = registry.unregister_definition("my-behavior", kind="behavior")

    assert returned_id == definition_id

    import yaml

    alias_data = yaml.safe_load((registry.home / "behaviors.yaml").read_text()) or {}
    assert "my-behavior" not in alias_data

    def_file = registry.home / "definitions" / f"{definition_id}.yaml"
    assert not def_file.exists()


# ---------------------------------------------------------------------------
# Tests for uninstall_environment()
# ---------------------------------------------------------------------------


def test_uninstall_environment_removes_directory(tmp_path: Path) -> None:
    """uninstall_environment() removes the environment directory and returns True."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    definition_id = "agent_test-agent_12345678"
    env_path = registry.get_environment_path(definition_id)
    env_path.mkdir(parents=True)
    assert env_path.is_dir()

    result = registry.uninstall_environment(definition_id)

    assert result is True
    assert not env_path.exists()


def test_uninstall_environment_returns_false_when_not_installed(
    tmp_path: Path,
) -> None:
    """uninstall_environment() returns False when the environment does not exist."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    result = registry.uninstall_environment("nonexistent-id")

    assert result is False
