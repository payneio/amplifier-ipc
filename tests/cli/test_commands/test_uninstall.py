"""Tests for commands/uninstall.py — remove an environment without unregistering."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Tests for the uninstall Click command
# ---------------------------------------------------------------------------


class TestUninstallRemovesEnvironment:
    def test_uninstall_known_agent_removes_environment(self, tmp_path: Path) -> None:
        """uninstall command resolves the agent and removes the environment."""
        from amplifier_ipc.cli.commands.uninstall import uninstall

        mock_registry = MagicMock()
        mock_registry.resolve_agent.return_value = (
            tmp_path / "definitions" / "agent_my-agent_12345678.yaml"
        )
        mock_registry.uninstall_environment.return_value = True

        home_dir = tmp_path / "amplifier_home"

        with patch(
            "amplifier_ipc.cli.commands.uninstall.Registry",
            return_value=mock_registry,
        ):
            runner = CliRunner()
            result = runner.invoke(uninstall, ["my-agent", "--home", str(home_dir)])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        # Should print the definition_id or a confirmation
        assert "my-agent" in result.output or "agent_my-agent_12345678" in result.output

    def test_uninstall_calls_uninstall_environment(self, tmp_path: Path) -> None:
        """uninstall command calls uninstall_environment with the definition_id."""
        from amplifier_ipc.cli.commands.uninstall import uninstall

        def_file_name = "agent_my-agent_12345678"
        mock_def_path = tmp_path / "definitions" / f"{def_file_name}.yaml"
        mock_def_path.parent.mkdir(parents=True, exist_ok=True)
        mock_def_path.write_text("type: agent\nlocal_ref: my-agent\n")

        mock_registry = MagicMock()
        mock_registry.resolve_agent.return_value = mock_def_path
        mock_registry.uninstall_environment.return_value = True

        home_dir = tmp_path / "amplifier_home"

        with patch(
            "amplifier_ipc.cli.commands.uninstall.Registry",
            return_value=mock_registry,
        ):
            runner = CliRunner()
            runner.invoke(uninstall, ["my-agent", "--home", str(home_dir)])

        mock_registry.uninstall_environment.assert_called_once_with(def_file_name)

    def test_uninstall_reports_not_installed_when_no_environment(
        self, tmp_path: Path
    ) -> None:
        """uninstall command prints 'not installed' when environment doesn't exist."""
        from amplifier_ipc.cli.commands.uninstall import uninstall

        mock_def_path = tmp_path / "definitions" / "agent_my-agent_12345678.yaml"
        mock_def_path.parent.mkdir(parents=True, exist_ok=True)
        mock_def_path.write_text("type: agent\nlocal_ref: my-agent\n")

        mock_registry = MagicMock()
        mock_registry.resolve_agent.return_value = mock_def_path
        mock_registry.uninstall_environment.return_value = False

        home_dir = tmp_path / "amplifier_home"

        with patch(
            "amplifier_ipc.cli.commands.uninstall.Registry",
            return_value=mock_registry,
        ):
            runner = CliRunner()
            result = runner.invoke(uninstall, ["my-agent", "--home", str(home_dir)])

        assert result.exit_code == 0
        assert "not installed" in result.output.lower()

    def test_uninstall_falls_back_to_behavior(self, tmp_path: Path) -> None:
        """uninstall falls back to resolve_behavior when resolve_agent raises."""
        from amplifier_ipc.cli.commands.uninstall import uninstall

        def_file_name = "behavior_my-beh_abcdefab"
        mock_def_path = tmp_path / "definitions" / f"{def_file_name}.yaml"
        mock_def_path.parent.mkdir(parents=True, exist_ok=True)
        mock_def_path.write_text("type: behavior\nlocal_ref: my-beh\n")

        mock_registry = MagicMock()
        mock_registry.resolve_agent.side_effect = FileNotFoundError("not an agent")
        mock_registry.resolve_behavior.return_value = mock_def_path
        mock_registry.uninstall_environment.return_value = True

        home_dir = tmp_path / "amplifier_home"

        with patch(
            "amplifier_ipc.cli.commands.uninstall.Registry",
            return_value=mock_registry,
        ):
            runner = CliRunner()
            result = runner.invoke(uninstall, ["my-beh", "--home", str(home_dir)])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}"
        )
        mock_registry.resolve_behavior.assert_called_once_with("my-beh")
        mock_registry.uninstall_environment.assert_called_once_with(def_file_name)


class TestUninstallUnknownName:
    def test_uninstall_unknown_name_shows_error(self, tmp_path: Path) -> None:
        """uninstall command shows an error when name is not in registry at all."""
        from amplifier_ipc.cli.commands.uninstall import uninstall

        mock_registry = MagicMock()
        mock_registry.resolve_agent.side_effect = FileNotFoundError("not an agent")
        mock_registry.resolve_behavior.side_effect = FileNotFoundError("not a behavior")

        home_dir = tmp_path / "amplifier_home"

        with patch(
            "amplifier_ipc.cli.commands.uninstall.Registry",
            return_value=mock_registry,
        ):
            runner = CliRunner()
            result = runner.invoke(uninstall, ["ghost", "--home", str(home_dir)])

        assert result.exit_code != 0, (
            f"Expected non-zero exit code. Output: {result.output}"
        )
        assert (
            "error" in result.output.lower() or "not found" in result.output.lower()
        ), f"Expected error message. Output: {result.output}"
