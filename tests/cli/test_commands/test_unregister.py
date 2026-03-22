"""Tests for commands/unregister.py — remove a definition and its environment."""

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
uuid: 12345678-abcd-ef00-0000-000000000000
name: My Test Agent
"""


# ---------------------------------------------------------------------------
# Tests for the unregister Click command
# ---------------------------------------------------------------------------


class TestUnregisterKnownAgent:
    def test_unregister_known_agent_succeeds(
        self, tmp_path: Path, agent_yaml_content: str
    ) -> None:
        """unregister command removes a registered agent and prints the definition id."""
        from amplifier_ipc.cli.commands.unregister import unregister

        mock_registry = MagicMock()
        mock_registry.unregister_definition.return_value = "agent_my-agent_12345678"
        mock_registry.uninstall_environment.return_value = True

        home_dir = tmp_path / "amplifier_home"

        with patch(
            "amplifier_ipc.cli.commands.unregister.Registry",
            return_value=mock_registry,
        ):
            runner = CliRunner()
            result = runner.invoke(unregister, ["my-agent", "--home", str(home_dir)])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        assert "agent_my-agent_12345678" in result.output
        mock_registry.unregister_definition.assert_called_once_with(
            "my-agent", kind="agent"
        )

    def test_unregister_also_removes_environment(self, tmp_path: Path) -> None:
        """unregister command calls uninstall_environment after unregistering."""
        from amplifier_ipc.cli.commands.unregister import unregister

        mock_registry = MagicMock()
        mock_registry.unregister_definition.return_value = "agent_my-agent_12345678"
        mock_registry.uninstall_environment.return_value = True

        home_dir = tmp_path / "amplifier_home"

        with patch(
            "amplifier_ipc.cli.commands.unregister.Registry",
            return_value=mock_registry,
        ):
            runner = CliRunner()
            runner.invoke(unregister, ["my-agent", "--home", str(home_dir)])

        mock_registry.uninstall_environment.assert_called_once_with(
            "agent_my-agent_12345678"
        )

    def test_unregister_behavior_uses_behavior_kind(self, tmp_path: Path) -> None:
        """unregister --type behavior passes kind='behavior' to registry."""
        from amplifier_ipc.cli.commands.unregister import unregister

        mock_registry = MagicMock()
        mock_registry.unregister_definition.return_value = "behavior_my-beh_abcdefab"
        mock_registry.uninstall_environment.return_value = False

        home_dir = tmp_path / "amplifier_home"

        with patch(
            "amplifier_ipc.cli.commands.unregister.Registry",
            return_value=mock_registry,
        ):
            runner = CliRunner()
            result = runner.invoke(
                unregister,
                ["my-beh", "--type", "behavior", "--home", str(home_dir)],
            )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}"
        )
        mock_registry.unregister_definition.assert_called_once_with(
            "my-beh", kind="behavior"
        )


class TestUnregisterUnknownName:
    def test_unregister_unknown_name_shows_error(self, tmp_path: Path) -> None:
        """unregister command shows an error when the name is not registered."""
        from amplifier_ipc.cli.commands.unregister import unregister

        mock_registry = MagicMock()
        mock_registry.unregister_definition.side_effect = FileNotFoundError(
            "agent 'ghost' not found in registry."
        )

        home_dir = tmp_path / "amplifier_home"

        with patch(
            "amplifier_ipc.cli.commands.unregister.Registry",
            return_value=mock_registry,
        ):
            runner = CliRunner()
            result = runner.invoke(unregister, ["ghost", "--home", str(home_dir)])

        assert result.exit_code != 0, (
            f"Expected non-zero exit code. Output: {result.output}"
        )
        assert "error" in result.output.lower() or "ghost" in result.output, (
            f"Expected error in output. Output: {result.output}"
        )
