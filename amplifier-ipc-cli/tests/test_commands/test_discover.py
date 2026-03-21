"""Tests for commands/discover.py - scan_location and discover Click command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent_yaml_content() -> str:
    return """\
type: agent
local_ref: my-agent
uuid: 12345678-abcd-efgh-ijkl-mnopqrstuvwx
name: My Test Agent
description: A test agent definition
"""


@pytest.fixture()
def behavior_yaml_content() -> str:
    return """\
type: behavior
local_ref: my-behavior
uuid: 87654321-dcba-hgfe-lkji-xwvutsrqponm
name: My Test Behavior
description: A test behavior definition
"""


# ---------------------------------------------------------------------------
# Tests for scan_location()
# ---------------------------------------------------------------------------


class TestScanLocationFindsAgentYaml:
    def test_scan_location_finds_agent_yaml(
        self, tmp_path: Path, agent_yaml_content: str
    ) -> None:
        """scan_location finds a .yaml file with type: agent."""
        from amplifier_ipc_cli.commands.discover import scan_location

        agent_file = tmp_path / "my_agent.yaml"
        agent_file.write_text(agent_yaml_content)

        results = scan_location(str(tmp_path))

        assert len(results) == 1
        item = results[0]
        assert item["type"] == "agent"
        assert item["local_ref"] == "my-agent"
        assert item["path"] == str(agent_file.resolve())
        assert "raw_content" in item


class TestScanLocationFindsBehaviorYaml:
    def test_scan_location_finds_behavior_yaml(
        self, tmp_path: Path, behavior_yaml_content: str
    ) -> None:
        """scan_location finds a .yaml file with type: behavior."""
        from amplifier_ipc_cli.commands.discover import scan_location

        behavior_file = tmp_path / "my_behavior.yml"
        behavior_file.write_text(behavior_yaml_content)

        results = scan_location(str(tmp_path))

        assert len(results) == 1
        item = results[0]
        assert item["type"] == "behavior"
        assert item["local_ref"] == "my-behavior"
        assert item["path"] == str(behavior_file.resolve())
        assert "raw_content" in item


class TestScanLocationFindsMultiple:
    def test_scan_location_finds_multiple(
        self,
        tmp_path: Path,
        agent_yaml_content: str,
        behavior_yaml_content: str,
    ) -> None:
        """scan_location finds multiple definitions in the same directory."""
        from amplifier_ipc_cli.commands.discover import scan_location

        (tmp_path / "agent.yaml").write_text(agent_yaml_content)
        (tmp_path / "behavior.yaml").write_text(behavior_yaml_content)

        results = scan_location(str(tmp_path))

        assert len(results) == 2
        types_found = {r["type"] for r in results}
        assert types_found == {"agent", "behavior"}


class TestScanLocationEmptyDirectory:
    def test_scan_location_empty_directory(self, tmp_path: Path) -> None:
        """scan_location returns an empty list for a directory with no YAML definitions."""
        from amplifier_ipc_cli.commands.discover import scan_location

        results = scan_location(str(tmp_path))

        assert results == []

    def test_scan_location_ignores_non_definition_yaml(self, tmp_path: Path) -> None:
        """scan_location ignores YAML files that have no type: agent/behavior."""
        from amplifier_ipc_cli.commands.discover import scan_location

        random_yaml = tmp_path / "config.yaml"
        random_yaml.write_text("key: value\nanother_key: 42\n")

        results = scan_location(str(tmp_path))

        assert results == []


class TestScanLocationRecursesSubdirectories:
    def test_scan_location_recurses_subdirectories(
        self, tmp_path: Path, agent_yaml_content: str
    ) -> None:
        """scan_location recursively finds YAML files in subdirectories."""
        from amplifier_ipc_cli.commands.discover import scan_location

        sub = tmp_path / "agents" / "nested"
        sub.mkdir(parents=True)
        nested_file = sub / "agent.yaml"
        nested_file.write_text(agent_yaml_content)

        results = scan_location(str(tmp_path))

        assert len(results) == 1
        assert results[0]["path"] == str(nested_file.resolve())


# ---------------------------------------------------------------------------
# Tests for the discover Click command
# ---------------------------------------------------------------------------


class TestDiscoverLocalPath:
    def test_discover_local_path(self, tmp_path: Path, agent_yaml_content: str) -> None:
        """discover command reports found definitions from a local path."""
        from amplifier_ipc_cli.commands.discover import discover

        (tmp_path / "agent.yaml").write_text(agent_yaml_content)

        runner = CliRunner()
        result = runner.invoke(discover, [str(tmp_path)])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        # Should report found definitions
        assert "my-agent" in result.output or "agent" in result.output


class TestDiscoverWithRegister:
    def test_discover_with_register(
        self, tmp_path: Path, agent_yaml_content: str
    ) -> None:
        """discover --register calls registry.register_definition for each found definition."""
        from amplifier_ipc_cli.commands.discover import discover

        (tmp_path / "agent.yaml").write_text(agent_yaml_content)

        home_dir = tmp_path / "amplifier_home"
        mock_registry = MagicMock()

        with patch(
            "amplifier_ipc_cli.commands.discover.Registry", return_value=mock_registry
        ) as mock_registry_cls:
            runner = CliRunner()
            result = runner.invoke(
                discover,
                [str(tmp_path), "--register", "--home", str(home_dir)],
            )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        # Registry should have been constructed
        mock_registry_cls.assert_called_once()
        # ensure_home should be called
        mock_registry.ensure_home.assert_called_once()
        # register_definition called for each found item
        mock_registry.register_definition.assert_called_once()


class TestDiscoverNoDefinitions:
    def test_discover_no_definitions(self, tmp_path: Path) -> None:
        """discover command reports when no definitions are found."""
        from amplifier_ipc_cli.commands.discover import discover

        runner = CliRunner()
        result = runner.invoke(discover, [str(tmp_path)])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        # Should indicate no definitions found
        assert (
            "0" in result.output
            or "no" in result.output.lower()
            or "found" in result.output.lower()
        )
