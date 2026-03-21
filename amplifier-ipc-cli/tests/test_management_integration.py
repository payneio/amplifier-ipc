"""End-to-end management flow integration tests.

Tests the full CLI lifecycle:
    discover → register → install → update → session lifecycle

All tests invoke the CLI via CliRunner using ``cli`` from
``amplifier_ipc_cli.main``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

from amplifier_ipc_cli.main import cli


# ---------------------------------------------------------------------------
# YAML sample definitions
# ---------------------------------------------------------------------------

_AGENT_YAML = """\
type: agent
local_ref: integration-agent
uuid: aaaa1111-bbbb-2222-3333-444455556666
orchestrator: loop
context_manager: simple
provider: anthropic
behaviors:
  - integration-beh
services:
  - name: integration-service
    source: integration-package>=1.0
"""

_BEHAVIOR_YAML = """\
type: behavior
local_ref: integration-beh
uuid: cccc3333-dddd-4444-5555-666677778888
description: Integration test behavior
"""


# ---------------------------------------------------------------------------
# Helper: create a test session directory
# ---------------------------------------------------------------------------


def _create_test_session(
    sessions_dir: Path,
    session_id: str,
    name: str = "Integration Test Session",
) -> Path:
    """Create a fake session directory with transcript.jsonl and metadata.json.

    Args:
        sessions_dir: Parent directory that holds all sessions.
        session_id:   Directory name / ID for this session.
        name:         Human-readable session name stored in metadata.

    Returns:
        Path to the created session directory.
    """
    session_dir = sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "session_id": session_id,
        "name": name,
        "status": "completed",
    }
    (session_dir / "metadata.json").write_text(json.dumps(metadata))

    messages = [
        {"role": "user", "content": "Hello from integration test"},
        {"role": "assistant", "content": "Hello back from assistant"},
    ]
    transcript_lines = "\n".join(json.dumps(m) for m in messages)
    (session_dir / "transcript.jsonl").write_text(transcript_lines)

    return session_dir


# ---------------------------------------------------------------------------
# Test 1 — discover and register a local directory
# ---------------------------------------------------------------------------


class TestDiscoverAndRegisterLocalDirectory:
    def test_discover_and_register_local_directory(self, tmp_path: Path) -> None:
        """Creates definition files, runs discover --register, verifies registry populated.

        Scenario:
        - Two YAML definition files (agent + behavior) in a temp directory.
        - ``cli discover <dir> --register --home <home>`` is invoked.
        - Exit code is 0.
        - Output contains "Found 2" and "Registered".
        - ``agents.yaml`` contains the "integration-agent" alias.
        - ``behaviors.yaml`` contains the "integration-beh" alias.
        """
        defs_dir = tmp_path / "definitions"
        defs_dir.mkdir()

        (defs_dir / "agent.yaml").write_text(_AGENT_YAML)
        (defs_dir / "behavior.yaml").write_text(_BEHAVIOR_YAML)

        home_dir = tmp_path / "amplifier_home"

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["discover", str(defs_dir), "--register", "--home", str(home_dir)],
        )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        assert "Found 2" in result.output, (
            f"Expected 'Found 2' in output:\n{result.output!r}"
        )
        assert "Registered" in result.output, (
            f"Expected 'Registered' in output:\n{result.output!r}"
        )

        # Verify agents.yaml contains the integration-agent alias
        agents_yaml_path = home_dir / "agents.yaml"
        assert agents_yaml_path.exists(), "agents.yaml should have been created"
        agents_data = yaml.safe_load(agents_yaml_path.read_text()) or {}
        assert "integration-agent" in agents_data, (
            f"Expected 'integration-agent' key in agents.yaml: {agents_data}"
        )

        # Verify behaviors.yaml contains the integration-beh alias
        behaviors_yaml_path = home_dir / "behaviors.yaml"
        assert behaviors_yaml_path.exists(), "behaviors.yaml should have been created"
        behaviors_data = yaml.safe_load(behaviors_yaml_path.read_text()) or {}
        assert "integration-beh" in behaviors_data, (
            f"Expected 'integration-beh' key in behaviors.yaml: {behaviors_data}"
        )


# ---------------------------------------------------------------------------
# Test 2 — register a single behavior file
# ---------------------------------------------------------------------------


class TestRegisterSingleBehavior:
    def test_register_single_behavior(self, tmp_path: Path) -> None:
        """Writes a behavior YAML, registers it via CLI, verifies alias in behaviors.yaml.

        Scenario:
        - One behavior YAML file written to a temp path.
        - ``cli register <file> --home <home>`` is invoked.
        - Exit code is 0.
        - ``behaviors.yaml`` contains the "integration-beh" alias.
        """
        behavior_file = tmp_path / "integration-beh.yaml"
        behavior_file.write_text(_BEHAVIOR_YAML)

        home_dir = tmp_path / "amplifier_home"

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["register", str(behavior_file), "--home", str(home_dir)],
        )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )

        # behaviors.yaml must contain the integration-beh alias after register
        behaviors_yaml_path = home_dir / "behaviors.yaml"
        assert behaviors_yaml_path.exists(), (
            "behaviors.yaml should have been created by register command"
        )
        behaviors_data = yaml.safe_load(behaviors_yaml_path.read_text()) or {}
        assert "integration-beh" in behaviors_data, (
            f"Expected 'integration-beh' alias in behaviors.yaml: {behaviors_data}"
        )


# ---------------------------------------------------------------------------
# Test 3 — install agent with _run_uv mocked
# ---------------------------------------------------------------------------


class TestInstallAgentWithMockedUv:
    def test_install_agent_with_mocked_uv(self, tmp_path: Path) -> None:
        """Pre-registers agent, installs it with _run_uv mocked, verifies success.

        Scenario:
        - Agent YAML is registered directly via Registry (bypasses CLI for setup).
        - ``cli install integration-agent --home <home>`` is invoked with
          ``_run_uv`` patched to a no-op.
        - Exit code is 0.
        - ``_run_uv`` is called exactly twice: once for venv, once for pip install.
        """
        from amplifier_ipc_cli.registry import Registry

        home_dir = tmp_path / "amplifier_home"

        # Pre-register the agent so the install command can resolve it
        registry = Registry(home=home_dir)
        registry.ensure_home()
        registry.register_definition(_AGENT_YAML)

        runner = CliRunner()
        with patch("amplifier_ipc_cli.commands.install._run_uv") as mock_run_uv:
            result = runner.invoke(
                cli,
                ["install", "integration-agent", "--home", str(home_dir)],
            )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        # install_service calls _run_uv twice: venv creation + pip install
        assert mock_run_uv.call_count == 2, (
            f"Expected _run_uv called twice (venv + pip install), "
            f"got {mock_run_uv.call_count} calls.\nOutput: {result.output}"
        )


# ---------------------------------------------------------------------------
# Test 4 — update check after local register (no _meta blocks)
# ---------------------------------------------------------------------------


class TestUpdateCheckAfterRegister:
    def test_update_check_after_register(self, tmp_path: Path) -> None:
        """Registers agent+behavior locally, runs update --check, sees no-source message.

        Scenario:
        - Agent and behavior YAMLs are registered (no _meta blocks → no remote URLs).
        - ``cli update integration-agent --check --home <home>`` is invoked.
        - Exit code is 0.
        - Output confirms that no behaviors with remote source URLs were found.
        """
        from amplifier_ipc_cli.registry import Registry

        home_dir = tmp_path / "amplifier_home"

        registry = Registry(home=home_dir)
        registry.ensure_home()
        registry.register_definition(_AGENT_YAML)
        registry.register_definition(_BEHAVIOR_YAML)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["update", "integration-agent", "--check", "--home", str(home_dir)],
        )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        # No behaviors have _meta.source_url → update reports no sources to check
        assert "No behaviors with source URLs found." in result.output, (
            f"Expected 'No behaviors with source URLs found.' in output:\n"
            f"{result.output!r}"
        )


# ---------------------------------------------------------------------------
# Test 5 — full session lifecycle
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    def test_session_lifecycle(self, tmp_path: Path) -> None:
        """Full session lifecycle: list (truncated ID) → show (full ID) → delete (gone).

        Scenario:
        - A test session directory is created with transcript.jsonl and metadata.json.
        - ``cli session --sessions-dir <dir> list`` shows the truncated session ID.
        - ``cli session --sessions-dir <dir> show <prefix>`` shows the full session ID.
        - ``cli session --sessions-dir <dir> delete <prefix> --force`` removes the directory.
        """
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        # Use a long, recognisable ID so we can test truncation in list output
        session_id = "integrationtest12345678abcdef"
        session_dir = _create_test_session(
            sessions_dir,
            session_id,
            name="Integration Lifecycle Session",
        )
        assert session_dir.exists(), (
            "Session directory should exist before lifecycle test"
        )

        runner = CliRunner()

        # -- Step 1: list sessions — truncated ID should appear ----------------
        result_list = runner.invoke(
            cli,
            ["session", "--sessions-dir", str(sessions_dir), "list"],
        )
        assert result_list.exit_code == 0, (
            f"list exit_code={result_list.exit_code}\n"
            f"Output: {result_list.output}\n"
            f"Exception: {result_list.exception}"
        )
        # Truncated ID is first 8 chars + "..." → "integrat..."
        truncated_prefix = session_id[:8]
        assert truncated_prefix in result_list.output, (
            f"Expected truncated ID prefix '{truncated_prefix}' in list output:\n"
            f"{result_list.output!r}"
        )

        # -- Step 2: show session by prefix — full ID should appear ------------
        prefix = session_id[:10]  # Unambiguous prefix (only one session exists)
        result_show = runner.invoke(
            cli,
            ["session", "--sessions-dir", str(sessions_dir), "show", prefix],
        )
        assert result_show.exit_code == 0, (
            f"show exit_code={result_show.exit_code}\n"
            f"Output: {result_show.output}\n"
            f"Exception: {result_show.exception}"
        )
        assert session_id in result_show.output, (
            f"Expected full session ID '{session_id}' in show output:\n"
            f"{result_show.output!r}"
        )

        # -- Step 3: delete session by prefix — directory should be gone -------
        result_delete = runner.invoke(
            cli,
            [
                "session",
                "--sessions-dir",
                str(sessions_dir),
                "delete",
                prefix,
                "--force",
            ],
        )
        assert result_delete.exit_code == 0, (
            f"delete exit_code={result_delete.exit_code}\n"
            f"Output: {result_delete.output}\n"
            f"Exception: {result_delete.exception}"
        )
        assert not session_dir.exists(), (
            f"Session directory should have been deleted: {session_dir}"
        )
