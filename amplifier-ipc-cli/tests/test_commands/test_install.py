"""Tests for commands/install.py — install an agent or behavior service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent_yaml_with_services() -> str:
    return """\
type: agent
local_ref: my-agent
uuid: 12345678-abcd-efgh-ijkl-mnopqrstuvwx
name: My Test Agent
description: A test agent with services
services:
  - name: my-service
    source: my-package>=1.0
"""


@pytest.fixture()
def behavior_yaml_with_services() -> str:
    return """\
type: behavior
local_ref: my-behavior
uuid: 87654321-dcba-hgfe-lkji-xwvutsrqponm
name: My Test Behavior
description: A test behavior with services
services:
  - name: my-behavior-service
    source: behavior-package>=2.0
"""


# ---------------------------------------------------------------------------
# Tests for install_service()
# ---------------------------------------------------------------------------


class TestInstallServiceCreatesVenv:
    def test_install_service_creates_venv(self, tmp_path: Path) -> None:
        """install_service calls _run_uv twice: once for venv, once for pip install."""
        from amplifier_ipc_cli.commands.install import install_service

        mock_registry = MagicMock()
        mock_registry.is_installed.return_value = False
        env_path = tmp_path / "environments" / "test-def-id"
        mock_registry.get_environment_path.return_value = env_path

        with patch("amplifier_ipc_cli.commands.install._run_uv") as mock_run_uv:
            install_service(mock_registry, "test-def-id", "some-package>=1.0")

        assert mock_run_uv.call_count == 2, (
            f"Expected _run_uv called twice, got {mock_run_uv.call_count}"
        )

        python_path = env_path / "bin" / "python"
        expected_calls = [
            call(["venv", str(env_path)]),
            call(["pip", "install", "--python", str(python_path), "some-package>=1.0"]),
        ]
        mock_run_uv.assert_has_calls(expected_calls)


class TestInstallServiceAlreadyInstalled:
    def test_install_service_already_installed(self, tmp_path: Path) -> None:
        """install_service skips installation when environment already exists (not force)."""
        from amplifier_ipc_cli.commands.install import install_service

        mock_registry = MagicMock()
        mock_registry.is_installed.return_value = True

        with patch("amplifier_ipc_cli.commands.install._run_uv") as mock_run_uv:
            install_service(mock_registry, "test-def-id", "some-package>=1.0")

        mock_run_uv.assert_not_called()

    def test_install_service_force_reinstalls_when_already_installed(
        self, tmp_path: Path
    ) -> None:
        """install_service runs installation even when already installed if force=True."""
        from amplifier_ipc_cli.commands.install import install_service

        mock_registry = MagicMock()
        mock_registry.is_installed.return_value = True
        env_path = tmp_path / "environments" / "test-def-id"
        mock_registry.get_environment_path.return_value = env_path

        with patch("amplifier_ipc_cli.commands.install._run_uv") as mock_run_uv:
            install_service(
                mock_registry, "test-def-id", "some-package>=1.0", force=True
            )

        assert mock_run_uv.call_count == 2


# ---------------------------------------------------------------------------
# Tests for the install Click command
# ---------------------------------------------------------------------------


class TestInstallCommandUnknownName:
    def test_install_command_unknown_name(self, tmp_path: Path) -> None:
        """install command shows an error when the name is not found in agent or behavior registry."""
        from amplifier_ipc_cli.commands.install import install

        mock_registry = MagicMock()
        mock_registry.resolve_agent.side_effect = FileNotFoundError(
            "agent 'unknown' not found"
        )
        mock_registry.resolve_behavior.side_effect = FileNotFoundError(
            "behavior 'unknown' not found"
        )

        home_dir = tmp_path / "amplifier_home"

        with patch(
            "amplifier_ipc_cli.commands.install.Registry", return_value=mock_registry
        ):
            runner = CliRunner()
            result = runner.invoke(install, ["unknown", "--home", str(home_dir)])

        assert result.exit_code != 0, (
            f"Expected non-zero exit code. Output: {result.output}"
        )
        assert (
            "error" in result.output.lower() or "not found" in result.output.lower()
        ), f"Expected error message in output. Output: {result.output}"


class TestInstallCommandCallsInstallService:
    def test_install_command_calls_install_service(
        self, tmp_path: Path, agent_yaml_with_services: str
    ) -> None:
        """install command resolves agent name and calls install_service for each service."""
        from amplifier_ipc_cli.commands.install import install

        # Create a definition file
        def_file = tmp_path / "agent_def.yaml"
        def_file.write_text(agent_yaml_with_services)

        mock_registry = MagicMock()
        mock_registry.resolve_agent.return_value = def_file
        env_path = tmp_path / "environments" / "my-def-id"
        mock_registry.get_environment_path.return_value = env_path
        mock_registry.is_installed.return_value = False

        home_dir = tmp_path / "amplifier_home"

        with (
            patch(
                "amplifier_ipc_cli.commands.install.Registry",
                return_value=mock_registry,
            ),
            patch("amplifier_ipc_cli.commands.install._run_uv") as mock_run_uv,
        ):
            runner = CliRunner()
            result = runner.invoke(install, ["my-agent", "--home", str(home_dir)])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        # Should have called _run_uv twice (venv + pip install) for the one service
        assert mock_run_uv.call_count == 2

    def test_install_command_falls_back_to_behavior(
        self, tmp_path: Path, behavior_yaml_with_services: str
    ) -> None:
        """install command falls back to resolve_behavior when resolve_agent raises FileNotFoundError."""
        from amplifier_ipc_cli.commands.install import install

        def_file = tmp_path / "behavior_def.yaml"
        def_file.write_text(behavior_yaml_with_services)

        mock_registry = MagicMock()
        mock_registry.resolve_agent.side_effect = FileNotFoundError("not an agent")
        mock_registry.resolve_behavior.return_value = def_file
        env_path = tmp_path / "environments" / "my-behavior-id"
        mock_registry.get_environment_path.return_value = env_path
        mock_registry.is_installed.return_value = False

        home_dir = tmp_path / "amplifier_home"

        with (
            patch(
                "amplifier_ipc_cli.commands.install.Registry",
                return_value=mock_registry,
            ),
            patch("amplifier_ipc_cli.commands.install._run_uv") as mock_run_uv,
        ):
            runner = CliRunner()
            result = runner.invoke(install, ["my-behavior", "--home", str(home_dir)])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        mock_registry.resolve_behavior.assert_called_once_with("my-behavior")
        # Should have called _run_uv twice for the one service
        assert mock_run_uv.call_count == 2
