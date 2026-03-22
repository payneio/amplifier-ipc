"""Tests for Registry class - manages $AMPLIFIER_HOME filesystem layout."""

from datetime import datetime
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
    from amplifier_ipc.host.definition_registry import Registry

    return Registry(home=home_dir)


AGENT_YAML = """\
agent:
  ref: my-agent
  uuid: 12345678-abcd-efgh-ijkl-mnopqrstuvwx
  name: My Test Agent
  description: A test agent definition
"""

BEHAVIOR_YAML = """\
behavior:
  ref: my-behavior
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

        # definition_id = agent_my-agent_<full-uuid>
        definition_id = "agent_my-agent_12345678-abcd-efgh-ijkl-mnopqrstuvwx"
        def_file = home_dir / "definitions" / f"{definition_id}.yaml"
        assert def_file.is_file(), f"definition file {def_file} should exist"

        # Verify the file contains the original YAML content (nested format)
        parsed = yaml.safe_load(def_file.read_text())
        assert "agent" in parsed
        assert parsed["agent"]["ref"] == "my-agent"

        # Verify agents.yaml alias updated
        agents_data = yaml.safe_load((home_dir / "agents.yaml").read_text())
        assert "my-agent" in agents_data, "alias 'my-agent' should be in agents.yaml"
        assert agents_data["my-agent"] == definition_id

    def test_register_behavior_definition(self, registry, home_dir: Path) -> None:
        """register_definition() writes behavior def to definitions/ and updates behaviors.yaml."""
        registry.ensure_home()
        registry.register_definition(BEHAVIOR_YAML)

        # definition_id = behavior_my-behavior_<full-uuid>
        definition_id = "behavior_my-behavior_87654321-dcba-hgfe-lkji-xwvutsrqponm"
        def_file = home_dir / "definitions" / f"{definition_id}.yaml"
        assert def_file.is_file(), f"definition file {def_file} should exist"

        parsed = yaml.safe_load(def_file.read_text())
        assert "behavior" in parsed
        assert parsed["behavior"]["ref"] == "my-behavior"

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

        definition_id = "agent_my-agent_12345678-abcd-efgh-ijkl-mnopqrstuvwx"
        def_file = home_dir / "definitions" / f"{definition_id}.yaml"
        parsed = yaml.safe_load(def_file.read_text())

        assert "_meta" in parsed, (
            "definition should have _meta block when source_url provided"
        )
        meta = parsed["_meta"]
        assert meta["source_url"] == source_url
        assert "sha256" in meta, "_meta should have sha256 field"
        assert meta["sha256"].startswith("sha256:"), (
            "sha256 field should start with 'sha256:'"
        )
        assert len(meta["sha256"]) > len("sha256:"), (
            "sha256 field should have hex digest"
        )
        assert "fetched_at" in meta, "_meta should have fetched_at timestamp"
        # fetched_at should be a valid ISO timestamp string — parse strictly
        fetched_at = meta["fetched_at"]
        assert isinstance(fetched_at, str)
        datetime.fromisoformat(fetched_at)  # raises ValueError if not valid ISO

    def test_register_same_definition_twice_is_idempotent(
        self, registry, home_dir: Path
    ) -> None:
        """Registering the same definition twice does not raise and result is consistent."""
        registry.ensure_home()
        registry.register_definition(AGENT_YAML)
        registry.register_definition(AGENT_YAML)

        definition_id = "agent_my-agent_12345678-abcd-efgh-ijkl-mnopqrstuvwx"
        def_file = home_dir / "definitions" / f"{definition_id}.yaml"
        assert def_file.is_file()

        # Alias still points to the same definition_id
        agents_data = yaml.safe_load((home_dir / "agents.yaml").read_text())
        assert agents_data["my-agent"] == definition_id

        # Only one entry in agents.yaml for this local_ref
        assert list(agents_data.values()).count(definition_id) == 1


class TestResolveAgent:
    def test_resolve_agent_returns_path(self, registry, home_dir: Path) -> None:
        """resolve_agent() returns Path to definition file for a known agent."""
        registry.ensure_home()
        registry.register_definition(AGENT_YAML)

        result = registry.resolve_agent("my-agent")

        definition_id = "agent_my-agent_12345678-abcd-efgh-ijkl-mnopqrstuvwx"
        expected = home_dir / "definitions" / f"{definition_id}.yaml"
        assert result == expected
        assert result.is_file()

    def test_resolve_agent_unknown_raises_file_not_found(
        self, registry, home_dir: Path
    ) -> None:
        """resolve_agent() raises FileNotFoundError for unknown agent name."""
        registry.ensure_home()

        with pytest.raises(FileNotFoundError) as exc_info:
            registry.resolve_agent("nonexistent-agent")

        assert "nonexistent-agent" in str(exc_info.value)
        assert "Run amplifier-ipc discover" in str(exc_info.value)


class TestResolveBehavior:
    def test_resolve_behavior_returns_path(self, registry, home_dir: Path) -> None:
        """resolve_behavior() returns Path to definition file for a known behavior."""
        registry.ensure_home()
        registry.register_definition(BEHAVIOR_YAML)

        result = registry.resolve_behavior("my-behavior")

        definition_id = "behavior_my-behavior_87654321-dcba-hgfe-lkji-xwvutsrqponm"
        expected = home_dir / "definitions" / f"{definition_id}.yaml"
        assert result == expected
        assert result.is_file()

    def test_resolve_behavior_unknown_raises_file_not_found(
        self, registry, home_dir: Path
    ) -> None:
        """resolve_behavior() raises FileNotFoundError for unknown behavior name."""
        registry.ensure_home()

        with pytest.raises(FileNotFoundError) as exc_info:
            registry.resolve_behavior("nonexistent-behavior")

        assert "nonexistent-behavior" in str(exc_info.value)
        assert "Run amplifier-ipc discover" in str(exc_info.value)


class TestGetEnvironmentPath:
    def test_get_environment_path_returns_expected_path(
        self, registry, home_dir: Path
    ) -> None:
        """get_environment_path() returns home/environments/<definition_id>."""
        definition_id = "agent_my-agent_12345678"
        result = registry.get_environment_path(definition_id)
        expected = home_dir / "environments" / definition_id
        assert result == expected


class TestIsInstalled:
    def test_is_installed_false_when_no_env(self, registry, home_dir: Path) -> None:
        """is_installed() returns False when environment directory does not exist."""
        registry.ensure_home()
        definition_id = "agent_my-agent_12345678"
        assert registry.is_installed(definition_id) is False

    def test_is_installed_true_when_env_exists(self, registry, home_dir: Path) -> None:
        """is_installed() returns True when environment directory exists."""
        registry.ensure_home()
        definition_id = "agent_my-agent_12345678"
        env_dir = home_dir / "environments" / definition_id
        env_dir.mkdir(parents=True)

        assert registry.is_installed(definition_id) is True


class TestGetSourceMeta:
    def test_get_source_meta_returns_meta_when_present(
        self, registry, home_dir: Path
    ) -> None:
        """get_source_meta() returns _meta dict when definition has source metadata."""
        registry.ensure_home()
        source_url = "https://example.com/agents/my-agent.yaml"
        registry.register_definition(AGENT_YAML, source_url=source_url)

        definition_id = "agent_my-agent_12345678-abcd-efgh-ijkl-mnopqrstuvwx"
        meta = registry.get_source_meta(definition_id)

        assert meta is not None
        assert meta["source_url"] == source_url
        assert "sha256" in meta
        assert "fetched_at" in meta

    def test_get_source_meta_returns_none_when_no_meta(
        self, registry, home_dir: Path
    ) -> None:
        """get_source_meta() returns None when definition has no _meta block."""
        registry.ensure_home()
        registry.register_definition(AGENT_YAML)  # no source_url => no _meta

        definition_id = "agent_my-agent_12345678-abcd-efgh-ijkl-mnopqrstuvwx"
        meta = registry.get_source_meta(definition_id)

        assert meta is None

    def test_get_source_meta_returns_none_for_nonexistent_definition(
        self, registry, home_dir: Path
    ) -> None:
        """get_source_meta() returns None for a definition_id that doesn't exist."""
        registry.ensure_home()

        meta = registry.get_source_meta("agent_nonexistent_00000000")

        assert meta is None
