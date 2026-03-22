"""Tests for commands/register.py — register a single definition file."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
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
# Tests
# ---------------------------------------------------------------------------


class TestRegisterLocalFile:
    def test_register_local_file(self, tmp_path: Path, agent_yaml_content: str) -> None:
        """register command registers a local agent YAML file and creates alias in agents.yaml."""
        from amplifier_ipc.cli.commands.register import register

        agent_file = tmp_path / "my_agent.yaml"
        agent_file.write_text(agent_yaml_content)

        home_dir = tmp_path / "amplifier_home"

        runner = CliRunner()
        result = runner.invoke(
            register,
            [str(agent_file), "--home", str(home_dir)],
        )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )

        # Should print "Registered: <definition_id>"
        assert "Registered:" in result.output

        # agents.yaml should exist and contain my-agent alias
        agents_yaml = home_dir / "agents.yaml"
        assert agents_yaml.exists(), "agents.yaml should have been created"
        alias_data = yaml.safe_load(agents_yaml.read_text())
        assert "my-agent" in alias_data, (
            f"Expected 'my-agent' in agents.yaml, got: {alias_data}"
        )


class TestRegisterNonexistentFile:
    def test_register_nonexistent_file(self, tmp_path: Path) -> None:
        """register command shows an error when the file does not exist."""
        from amplifier_ipc.cli.commands.register import register

        nonexistent = tmp_path / "does_not_exist.yaml"

        runner = CliRunner()
        result = runner.invoke(register, [str(nonexistent)])

        # Should exit with non-zero exit code or show error
        assert result.exit_code != 0 or "error" in result.output.lower(), (
            f"Expected error for nonexistent file.\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )


class TestRegisterInvalidYaml:
    def test_register_invalid_yaml(self, tmp_path: Path) -> None:
        """register command shows an error when the YAML is missing required fields."""
        from amplifier_ipc.cli.commands.register import register

        # YAML that lacks type, local_ref, uuid fields
        bad_yaml_file = tmp_path / "bad.yaml"
        bad_yaml_file.write_text("key: value\nanother_key: 42\n")

        home_dir = tmp_path / "amplifier_home"

        runner = CliRunner()
        result = runner.invoke(
            register,
            [str(bad_yaml_file), "--home", str(home_dir)],
        )

        # Should exit with non-zero exit code or show error
        assert result.exit_code != 0 or "error" in result.output.lower(), (
            f"Expected error for invalid YAML.\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )


class TestRegisterBehavior:
    def test_register_behavior(
        self, tmp_path: Path, behavior_yaml_content: str
    ) -> None:
        """register command registers a behavior YAML and creates alias in behaviors.yaml."""
        from amplifier_ipc.cli.commands.register import register

        behavior_file = tmp_path / "my_behavior.yaml"
        behavior_file.write_text(behavior_yaml_content)

        home_dir = tmp_path / "amplifier_home"

        runner = CliRunner()
        result = runner.invoke(
            register,
            [str(behavior_file), "--home", str(home_dir)],
        )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )

        # Should print "Registered: <definition_id>"
        assert "Registered:" in result.output

        # behaviors.yaml should exist and contain my-behavior alias
        behaviors_yaml = home_dir / "behaviors.yaml"
        assert behaviors_yaml.exists(), "behaviors.yaml should have been created"
        alias_data = yaml.safe_load(behaviors_yaml.read_text())
        assert "my-behavior" in alias_data, (
            f"Expected 'my-behavior' in behaviors.yaml, got: {alias_data}"
        )
