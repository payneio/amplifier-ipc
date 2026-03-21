"""Tests for Registry class - manages $AMPLIFIER_HOME filesystem layout."""

from pathlib import Path

import pytest
import yaml


@pytest.fixture()
def home_dir(tmp_path: Path) -> Path:
    """Return a temporary directory to use as AMPLIFIER_HOME."""
    return tmp_path / "amplifier_home"


@pytest.fixture()
def registry(home_dir: Path):
    """Return a Registry instance with a temporary home directory."""
    from amplifier_ipc_cli.registry import Registry

    return Registry(home=home_dir)


AGENT_YAML = """\
type: agent
local_ref: my-agent
uuid: 12345678-abcd-efgh-ijkl-mnopqrstuvwx
name: My Test Agent
description: A test agent definition
"""

BEHAVIOR_YAML = """\
type: behavior
local_ref: my-behavior
uuid: 87654321-dcba-hgfe-lkji-xwvutsrqponm
name: My Test Behavior
description: A test behavior definition
"""


class TestEnsureHome:
    def test_ensure_home_creates_directory_structure(
        self, registry, home_dir: Path
    ) -> None:
        """ensure_home() creates home/, definitions/, environments/ dirs and alias files."""
        registry.ensure_home()

        # Directories
        assert home_dir.is_dir(), "home directory should be created"
        assert (home_dir / "definitions").is_dir(), "definitions/ should be created"
        assert (home_dir / "environments").is_dir(), "environments/ should be created"

        # Alias files initialized with {}
        agents_yaml = home_dir / "agents.yaml"
        behaviors_yaml = home_dir / "behaviors.yaml"
        assert agents_yaml.is_file(), "agents.yaml should be created"
        assert behaviors_yaml.is_file(), "behaviors.yaml should be created"

        agents_data = yaml.safe_load(agents_yaml.read_text())
        behaviors_data = yaml.safe_load(behaviors_yaml.read_text())
        assert agents_data == {} or agents_data is None
        assert behaviors_data == {} or behaviors_data is None

    def test_ensure_home_is_idempotent(self, registry, home_dir: Path) -> None:
        """Calling ensure_home() twice does not raise and leaves files intact."""
        registry.ensure_home()

        # Write something into agents.yaml to verify it isn't overwritten
        agents_yaml = home_dir / "agents.yaml"
        agents_yaml.write_text(
            yaml.dump({"existing-agent": "agent_existing-agent_abcd1234"})
        )
        original_content = agents_yaml.read_text()

        # Second call should not overwrite existing files
        registry.ensure_home()

        assert agents_yaml.read_text() == original_content, (
            "ensure_home() should not overwrite existing alias files"
        )
        assert (home_dir / "definitions").is_dir()
        assert (home_dir / "environments").is_dir()


class TestRegisterDefinition:
    def test_register_agent_definition(self, registry, home_dir: Path) -> None:
        """register_definition() writes agent def to definitions/<id>.yaml and updates agents.yaml."""
        registry.ensure_home()
        registry.register_definition(AGENT_YAML)

        # definition_id = agent_my-agent_12345678
        definition_id = "agent_my-agent_12345678"
        def_file = home_dir / "definitions" / f"{definition_id}.yaml"
        assert def_file.is_file(), f"definition file {def_file} should exist"

        # Verify the file contains the original YAML content
        parsed = yaml.safe_load(def_file.read_text())
        assert parsed["type"] == "agent"
        assert parsed["local_ref"] == "my-agent"

        # Verify agents.yaml alias updated
        agents_data = yaml.safe_load((home_dir / "agents.yaml").read_text())
        assert "my-agent" in agents_data, "alias 'my-agent' should be in agents.yaml"
        assert agents_data["my-agent"] == definition_id

    def test_register_behavior_definition(self, registry, home_dir: Path) -> None:
        """register_definition() writes behavior def to definitions/ and updates behaviors.yaml."""
        registry.ensure_home()
        registry.register_definition(BEHAVIOR_YAML)

        # definition_id = behavior_my-behavior_87654321
        definition_id = "behavior_my-behavior_87654321"
        def_file = home_dir / "definitions" / f"{definition_id}.yaml"
        assert def_file.is_file(), f"definition file {def_file} should exist"

        parsed = yaml.safe_load(def_file.read_text())
        assert parsed["type"] == "behavior"
        assert parsed["local_ref"] == "my-behavior"

        # Verify behaviors.yaml alias updated (NOT agents.yaml)
        behaviors_data = yaml.safe_load((home_dir / "behaviors.yaml").read_text())
        assert "my-behavior" in behaviors_data
        assert behaviors_data["my-behavior"] == definition_id

        # agents.yaml should remain empty
        agents_data = yaml.safe_load((home_dir / "agents.yaml").read_text())
        assert not agents_data or "my-behavior" not in agents_data

    def test_register_definition_with_source_url(
        self, registry, home_dir: Path
    ) -> None:
        """When source_url provided, definition file has _meta block."""
        registry.ensure_home()
        source_url = "https://example.com/agents/my-agent.yaml"
        registry.register_definition(AGENT_YAML, source_url=source_url)

        definition_id = "agent_my-agent_12345678"
        def_file = home_dir / "definitions" / f"{definition_id}.yaml"
        parsed = yaml.safe_load(def_file.read_text())

        assert "_meta" in parsed, (
            "definition should have _meta block when source_url provided"
        )
        meta = parsed["_meta"]
        assert meta["source_url"] == source_url
        assert "source_hash" in meta, "_meta should have source_hash"
        assert meta["source_hash"].startswith("sha256:"), (
            "source_hash should start with 'sha256:'"
        )
        assert len(meta["source_hash"]) > len("sha256:"), (
            "source_hash should have hex digest"
        )
        assert "fetched_at" in meta, "_meta should have fetched_at timestamp"
        # fetched_at should be a valid ISO timestamp string
        fetched_at = meta["fetched_at"]
        assert isinstance(fetched_at, str)
        assert "T" in fetched_at or "-" in fetched_at, "fetched_at should be ISO format"

    def test_register_same_definition_twice_is_idempotent(
        self, registry, home_dir: Path
    ) -> None:
        """Registering the same definition twice does not raise and result is consistent."""
        registry.ensure_home()
        registry.register_definition(AGENT_YAML)
        registry.register_definition(AGENT_YAML)

        definition_id = "agent_my-agent_12345678"
        def_file = home_dir / "definitions" / f"{definition_id}.yaml"
        assert def_file.is_file()

        # Alias still points to the same definition_id
        agents_data = yaml.safe_load((home_dir / "agents.yaml").read_text())
        assert agents_data["my-agent"] == definition_id

        # Only one entry in agents.yaml for this local_ref
        assert list(agents_data.values()).count(definition_id) == 1
