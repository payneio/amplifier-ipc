"""Tests for commands/install.py — install an agent or behavior service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Fixtures — new nested agent:/behavior: format with singular service:
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent_yaml_with_service() -> str:
    """New nested format: agent: wrapper with singular service: dict."""
    return """\
agent:
  service:
    source: my-package>=1.0
    command: my-command
"""


@pytest.fixture()
def behavior_yaml_with_service() -> str:
    """New nested format: behavior: wrapper with singular service: dict."""
    return """\
behavior:
  service:
    source: behavior-package>=2.0
    command: my-behavior-command
"""


# ---------------------------------------------------------------------------
# Tests for install_service()
# ---------------------------------------------------------------------------


class TestInstallServiceCreatesVenv:
    def test_install_service_creates_venv(self, tmp_path: Path) -> None:
        """install_service calls _run_uv twice: once for venv, once for pip install."""
        from amplifier_ipc.cli.commands.install import install_service

        mock_registry = MagicMock()
        mock_registry.is_installed.return_value = False
        env_path = tmp_path / "environments" / "test-def-id"
        mock_registry.get_environment_path.return_value = env_path

        with patch("amplifier_ipc.cli.commands.install._run_uv") as mock_run_uv:
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
        from amplifier_ipc.cli.commands.install import install_service

        mock_registry = MagicMock()
        mock_registry.is_installed.return_value = True

        with patch("amplifier_ipc.cli.commands.install._run_uv") as mock_run_uv:
            install_service(mock_registry, "test-def-id", "some-package>=1.0")

        mock_run_uv.assert_not_called()

    def test_install_service_force_reinstalls_when_already_installed(
        self, tmp_path: Path
    ) -> None:
        """install_service runs installation even when already installed if force=True."""
        from amplifier_ipc.cli.commands.install import install_service

        mock_registry = MagicMock()
        mock_registry.is_installed.return_value = True
        env_path = tmp_path / "environments" / "test-def-id"
        mock_registry.get_environment_path.return_value = env_path

        with patch("amplifier_ipc.cli.commands.install._run_uv") as mock_run_uv:
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
        from amplifier_ipc.cli.commands.install import install

        mock_registry = MagicMock()
        mock_registry.resolve_agent.side_effect = FileNotFoundError(
            "agent 'unknown' not found"
        )
        mock_registry.resolve_behavior.side_effect = FileNotFoundError(
            "behavior 'unknown' not found"
        )

        home_dir = tmp_path / "amplifier_home"

        with patch(
            "amplifier_ipc.cli.commands.install.Registry", return_value=mock_registry
        ):
            runner = CliRunner()
            result = runner.invoke(install, ["unknown", "--home", str(home_dir)])

        assert result.exit_code != 0, (
            f"Expected non-zero exit code. Output: {result.output}"
        )
        assert (
            "error" in result.output.lower() or "not found" in result.output.lower()
        ), f"Expected error message in output. Output: {result.output}"


class TestInstallCommandNestedAgentServiceFormat:
    """Tests for the new nested agent:/behavior: wrapper with singular service: format."""

    def test_install_command_reads_nested_agent_service(
        self, tmp_path: Path, agent_yaml_with_service: str
    ) -> None:
        """install command reads singular service: from agent: wrapper."""
        from amplifier_ipc.cli.commands.install import install

        def_file = tmp_path / "my-agent.yaml"
        def_file.write_text(agent_yaml_with_service)

        mock_registry = MagicMock()
        mock_registry.resolve_agent.return_value = def_file
        env_path = tmp_path / "environments" / "my-agent"
        mock_registry.get_environment_path.return_value = env_path
        mock_registry.is_installed.return_value = False

        home_dir = tmp_path / "amplifier_home"

        with (
            patch(
                "amplifier_ipc.cli.commands.install.Registry",
                return_value=mock_registry,
            ),
            patch("amplifier_ipc.cli.commands.install._run_uv") as mock_run_uv,
        ):
            runner = CliRunner()
            result = runner.invoke(install, ["my-agent", "--home", str(home_dir)])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        assert mock_run_uv.call_count == 2, (
            f"Expected _run_uv called twice, got {mock_run_uv.call_count}. "
            f"Output: {result.output}"
        )
        assert "my-command" in result.output, (
            f"Expected command name 'my-command' in output. Output: {result.output}"
        )

    def test_install_command_falls_back_to_behavior_nested_format(
        self, tmp_path: Path, behavior_yaml_with_service: str
    ) -> None:
        """install command falls back to resolve_behavior and reads behavior: wrapper."""
        from amplifier_ipc.cli.commands.install import install

        def_file = tmp_path / "behavior_def.yaml"
        def_file.write_text(behavior_yaml_with_service)

        mock_registry = MagicMock()
        mock_registry.resolve_agent.side_effect = FileNotFoundError("not an agent")
        mock_registry.resolve_behavior.return_value = def_file
        env_path = tmp_path / "environments" / "my-behavior-id"
        mock_registry.get_environment_path.return_value = env_path
        mock_registry.is_installed.return_value = False

        home_dir = tmp_path / "amplifier_home"

        with (
            patch(
                "amplifier_ipc.cli.commands.install.Registry",
                return_value=mock_registry,
            ),
            patch("amplifier_ipc.cli.commands.install._run_uv") as mock_run_uv,
        ):
            runner = CliRunner()
            result = runner.invoke(install, ["my-behavior", "--home", str(home_dir)])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        mock_registry.resolve_behavior.assert_called_once_with("my-behavior")
        assert mock_run_uv.call_count == 2, (
            f"Expected _run_uv called twice, got {mock_run_uv.call_count}. "
            f"Output: {result.output}"
        )
        assert "my-behavior-command" in result.output

    def test_install_command_no_service_in_definition(self, tmp_path: Path) -> None:
        """install command prints info and exits cleanly when no service: key found."""
        from amplifier_ipc.cli.commands.install import install

        def_file = tmp_path / "my-agent.yaml"
        def_file.write_text("agent:\n  description: no service here\n")

        mock_registry = MagicMock()
        mock_registry.resolve_agent.return_value = def_file

        home_dir = tmp_path / "amplifier_home"

        with (
            patch(
                "amplifier_ipc.cli.commands.install.Registry",
                return_value=mock_registry,
            ),
            patch("amplifier_ipc.cli.commands.install._run_uv") as mock_run_uv,
        ):
            runner = CliRunner()
            result = runner.invoke(install, ["my-agent", "--home", str(home_dir)])

        assert result.exit_code == 0
        mock_run_uv.assert_not_called()
        assert "No service to install" in result.output

    def test_install_command_no_source_in_service(self, tmp_path: Path) -> None:
        """install command skips installation when service: has no source."""
        from amplifier_ipc.cli.commands.install import install

        def_file = tmp_path / "my-agent.yaml"
        def_file.write_text("agent:\n  service:\n    command: my-cmd\n")

        mock_registry = MagicMock()
        mock_registry.resolve_agent.return_value = def_file

        home_dir = tmp_path / "amplifier_home"

        with (
            patch(
                "amplifier_ipc.cli.commands.install.Registry",
                return_value=mock_registry,
            ),
            patch("amplifier_ipc.cli.commands.install._run_uv") as mock_run_uv,
        ):
            runner = CliRunner()
            result = runner.invoke(install, ["my-agent", "--home", str(home_dir)])

        assert result.exit_code == 0
        mock_run_uv.assert_not_called()
        assert "Skipping service" in result.output

    def test_install_command_uses_name_as_command_fallback(
        self, tmp_path: Path
    ) -> None:
        """install command echoes name when service: has no command key."""
        from amplifier_ipc.cli.commands.install import install

        def_file = tmp_path / "my-agent.yaml"
        def_file.write_text("agent:\n  service:\n    source: some-package>=1.0\n")

        mock_registry = MagicMock()
        mock_registry.resolve_agent.return_value = def_file
        env_path = tmp_path / "environments" / "my-agent"
        mock_registry.get_environment_path.return_value = env_path
        mock_registry.is_installed.return_value = False

        home_dir = tmp_path / "amplifier_home"

        with (
            patch(
                "amplifier_ipc.cli.commands.install.Registry",
                return_value=mock_registry,
            ),
            patch("amplifier_ipc.cli.commands.install._run_uv"),
        ):
            runner = CliRunner()
            result = runner.invoke(install, ["my-agent", "--home", str(home_dir)])

        assert result.exit_code == 0
        # Falls back to CLI name argument when command is absent
        assert "my-agent" in result.output

    def test_install_command_definition_id_is_file_stem(
        self, tmp_path: Path, agent_yaml_with_service: str
    ) -> None:
        """install command derives definition_id from file stem."""
        from amplifier_ipc.cli.commands.install import install

        def_file = tmp_path / "some-unique-stem.yaml"
        def_file.write_text(agent_yaml_with_service)

        mock_registry = MagicMock()
        mock_registry.resolve_agent.return_value = def_file
        env_path = tmp_path / "environments" / "some-unique-stem"
        mock_registry.get_environment_path.return_value = env_path
        mock_registry.is_installed.return_value = False

        home_dir = tmp_path / "amplifier_home"

        with (
            patch(
                "amplifier_ipc.cli.commands.install.Registry",
                return_value=mock_registry,
            ),
            patch("amplifier_ipc.cli.commands.install._run_uv"),
        ):
            runner = CliRunner()
            result = runner.invoke(install, ["some-agent", "--home", str(home_dir)])

        assert result.exit_code == 0
        # Verify install_service was called with definition_id = file stem
        mock_registry.get_environment_path.assert_called_once_with("some-unique-stem")
