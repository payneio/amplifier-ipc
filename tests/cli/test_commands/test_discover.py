"""Tests for commands/discover.py - scan_location and discover Click command."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent_yaml_content() -> str:
    return """\
agent:
  ref: my-agent
  uuid: 12345678-abcd-efgh-ijkl-mnopqrstuvwx
  name: My Test Agent
  description: A test agent definition
"""


@pytest.fixture()
def behavior_yaml_content() -> str:
    return """\
behavior:
  ref: my-behavior
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
        """scan_location finds a .yaml file with agent: top-level key."""
        from amplifier_ipc.cli.commands.discover import scan_location

        agent_file = tmp_path / "my_agent.yaml"
        agent_file.write_text(agent_yaml_content)

        results = scan_location(str(tmp_path))

        assert len(results) == 1
        item = results[0]
        assert item["type"] == "agent"
        assert item["ref"] == "my-agent"
        assert item["path"] == str(agent_file.resolve())
        assert "raw_content" in item


class TestScanLocationFindsBehaviorYaml:
    def test_scan_location_finds_behavior_yaml(
        self, tmp_path: Path, behavior_yaml_content: str
    ) -> None:
        """scan_location finds a .yaml file with behavior: top-level key."""
        from amplifier_ipc.cli.commands.discover import scan_location

        behavior_file = tmp_path / "my_behavior.yml"
        behavior_file.write_text(behavior_yaml_content)

        results = scan_location(str(tmp_path))

        assert len(results) == 1
        item = results[0]
        assert item["type"] == "behavior"
        assert item["ref"] == "my-behavior"
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
        from amplifier_ipc.cli.commands.discover import scan_location

        (tmp_path / "agent.yaml").write_text(agent_yaml_content)
        (tmp_path / "behavior.yaml").write_text(behavior_yaml_content)

        results = scan_location(str(tmp_path))

        assert len(results) == 2
        types_found = {r["type"] for r in results}
        assert types_found == {"agent", "behavior"}


class TestScanLocationEmptyDirectory:
    def test_scan_location_empty_directory(self, tmp_path: Path) -> None:
        """scan_location returns an empty list for a directory with no YAML definitions."""
        from amplifier_ipc.cli.commands.discover import scan_location

        results = scan_location(str(tmp_path))

        assert results == []

    def test_scan_location_ignores_non_definition_yaml(self, tmp_path: Path) -> None:
        """scan_location ignores YAML files that have no agent:/behavior: top-level key."""
        from amplifier_ipc.cli.commands.discover import scan_location

        random_yaml = tmp_path / "config.yaml"
        random_yaml.write_text("key: value\nanother_key: 42\n")

        results = scan_location(str(tmp_path))

        assert results == []


class TestScanLocationRecursesSubdirectories:
    def test_scan_location_recurses_subdirectories(
        self, tmp_path: Path, agent_yaml_content: str
    ) -> None:
        """scan_location recursively finds YAML files in subdirectories."""
        from amplifier_ipc.cli.commands.discover import scan_location

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
        from amplifier_ipc.cli.commands.discover import discover

        (tmp_path / "agent.yaml").write_text(agent_yaml_content)

        runner = CliRunner()
        result = runner.invoke(discover, [str(tmp_path)])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        # Should report found definitions with the ref value
        assert "my-agent" in result.output


class TestDiscoverWithRegister:
    def test_discover_with_register(
        self, tmp_path: Path, agent_yaml_content: str
    ) -> None:
        """discover --register calls registry.register_definition for each found definition."""
        from amplifier_ipc.cli.commands.discover import discover

        (tmp_path / "agent.yaml").write_text(agent_yaml_content)

        home_dir = tmp_path / "amplifier_home"
        mock_registry = MagicMock()

        with patch(
            "amplifier_ipc.cli.commands.discover.Registry", return_value=mock_registry
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


class TestDiscoverGitUrlCleansUp:
    def test_discover_git_url_cleans_up_temp_dir(self, agent_yaml_content: str) -> None:
        """discover cleans up the temporary clone directory after scanning a git URL."""
        from amplifier_ipc.cli.commands.discover import discover

        captured_dirs: list[str] = []

        def fake_git_run(cmd: list[Any], **_: Any) -> None:
            # cmd = ["git", "clone", "--depth", "1", url, tmp_dir]
            tmp_dir = cmd[-1]
            captured_dirs.append(tmp_dir)
            Path(tmp_dir).mkdir(parents=True, exist_ok=True)
            (Path(tmp_dir) / "agent.yaml").write_text(agent_yaml_content)

        runner = CliRunner()
        with patch("subprocess.run", side_effect=fake_git_run):
            result = runner.invoke(discover, ["git+https://github.com/example/repo"])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        assert captured_dirs, "No temp directory was created during git clone"
        for tmp_dir in captured_dirs:
            assert not Path(tmp_dir).exists(), (
                f"Temp directory {tmp_dir} was not cleaned up after discover"
            )


class TestDiscoverNoDefinitions:
    def test_discover_no_definitions(self, tmp_path: Path) -> None:
        """discover command reports when no definitions are found."""
        from amplifier_ipc.cli.commands.discover import discover

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


# ---------------------------------------------------------------------------
# Tests for silent parse error logging
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests for discover --install
# ---------------------------------------------------------------------------


class TestDiscoverInstallWithoutRegisterFails:
    def test_discover_install_without_register_fails(self, tmp_path: Path) -> None:
        """--install without --register must show a clear error and exit non-zero."""
        from amplifier_ipc.cli.commands.discover import discover

        runner = CliRunner()
        result = runner.invoke(discover, [str(tmp_path), "--install"])

        assert result.exit_code != 0, f"Expected non-zero exit. Output: {result.output}"
        assert (
            "register" in result.output.lower() or "error" in result.output.lower()
        ), f"Expected error mentioning --register. Output: {result.output}"


class TestDiscoverInstallCreatesEnvironments:
    def test_discover_install_creates_environments(self, tmp_path: Path) -> None:
        """--register --install calls install_service for definitions with a service: block."""
        from amplifier_ipc.cli.commands.discover import discover

        agent_with_service = """\
agent:
  ref: my-service-agent
  uuid: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
  service:
    source: my-package>=1.0
    command: my-command
"""
        (tmp_path / "agent.yaml").write_text(agent_with_service)
        home_dir = tmp_path / "amplifier_home"

        mock_registry = MagicMock()
        mock_registry.register_definition.return_value = (
            "agent_my-service-agent_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        )

        with (
            patch(
                "amplifier_ipc.cli.commands.discover.Registry",
                return_value=mock_registry,
            ),
            patch(
                "amplifier_ipc.cli.commands.discover.install_service"
            ) as mock_install_service,
        ):
            runner = CliRunner()
            result = runner.invoke(
                discover,
                [str(tmp_path), "--register", "--install", "--home", str(home_dir)],
            )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        mock_install_service.assert_called_once_with(
            mock_registry,
            "agent_my-service-agent_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "my-package>=1.0",
        )
        assert "install" in result.output.lower(), (
            f"Expected install feedback in output. Output: {result.output}"
        )


class TestDiscoverInstallSkipsContentOnly:
    def test_discover_install_skips_content_only(self, tmp_path: Path) -> None:
        """--register --install skips definitions that have no service: block."""
        from amplifier_ipc.cli.commands.discover import discover

        content_only = """\
agent:
  ref: content-agent
  uuid: 11111111-2222-3333-4444-555555555555
  description: Just a content agent, no service
"""
        (tmp_path / "agent.yaml").write_text(content_only)
        home_dir = tmp_path / "amplifier_home"

        mock_registry = MagicMock()
        mock_registry.register_definition.return_value = (
            "agent_content-agent_11111111-2222-3333-4444-555555555555"
        )

        with (
            patch(
                "amplifier_ipc.cli.commands.discover.Registry",
                return_value=mock_registry,
            ),
            patch(
                "amplifier_ipc.cli.commands.discover.install_service"
            ) as mock_install_service,
        ):
            runner = CliRunner()
            result = runner.invoke(
                discover,
                [str(tmp_path), "--register", "--install", "--home", str(home_dir)],
            )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        mock_install_service.assert_not_called()


class TestTryParseDefinitionLogsOnError:
    def test_malformed_yaml_emits_debug_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_try_parse_definition must emit a debug log when YAML fails to parse.

        Silent failure in production makes malformed YAML invisible.  A debug
        log (including the file path and exception) lets developers diagnose
        scan issues without surfacing noise to end users.
        """
        import logging

        from amplifier_ipc.cli.commands.discover import _try_parse_definition

        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_bytes(b"\xff\xfe invalid utf-8 \x00 and null bytes")

        results: list = []
        with caplog.at_level(
            logging.DEBUG, logger="amplifier_ipc.cli.commands.discover"
        ):
            _try_parse_definition(bad_yaml, results)

        # Must not add anything to results
        assert results == []

        # Must emit at least one debug log mentioning the file
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1, (
            "_try_parse_definition must log a debug message when YAML parsing fails"
        )
        assert (
            str(bad_yaml) in debug_records[0].getMessage()
            or str(bad_yaml.name) in debug_records[0].message
        )
