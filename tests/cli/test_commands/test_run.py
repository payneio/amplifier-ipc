"""Tests for commands/run.py - the run command and CLI wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Test 1: test_run_no_agent_shows_error
# ---------------------------------------------------------------------------


class TestRunNoAgentShowsError:
    def test_run_no_agent_shows_error(self) -> None:
        """Running 'run' without --agent should show an error."""
        from amplifier_ipc.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["run"])

        assert result.exit_code != 0
        # Click should show a missing option error
        assert "agent" in result.output.lower() or "missing" in result.output.lower()


# ---------------------------------------------------------------------------
# Test 2: test_run_with_agent_invokes_launcher
# ---------------------------------------------------------------------------


class TestRunWithAgentInvokesLauncher:
    def test_run_with_agent_invokes_launcher(self) -> None:
        """run --agent foundation should invoke _run_agent with the agent name."""
        from amplifier_ipc.cli.main import cli

        runner = CliRunner()

        with patch(
            "amplifier_ipc.cli.commands.run._run_agent", new_callable=AsyncMock
        ) as mock_run_agent:
            result = runner.invoke(cli, ["run", "--agent", "foundation"])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}"
        )
        mock_run_agent.assert_called_once()
        call_kwargs = mock_run_agent.call_args
        # The agent name should be passed
        args, kwargs = call_kwargs
        assert "foundation" in args or kwargs.get("agent_name") == "foundation"


# ---------------------------------------------------------------------------
# Test 3: test_run_with_message_passes_prompt
# ---------------------------------------------------------------------------


class TestRunWithMessagePassesPrompt:
    def test_run_with_message_passes_prompt(self) -> None:
        """run --agent foundation 'hello' passes the message as the prompt."""
        from amplifier_ipc.cli.main import cli

        runner = CliRunner()

        with patch(
            "amplifier_ipc.cli.commands.run._run_agent", new_callable=AsyncMock
        ) as mock_run_agent:
            result = runner.invoke(cli, ["run", "--agent", "foundation", "hello"])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}"
        )
        mock_run_agent.assert_called_once()
        args, kwargs = mock_run_agent.call_args
        # The message should be passed as prompt
        assert "hello" in args or kwargs.get("message") == "hello"


# ---------------------------------------------------------------------------
# Test 4: test_cli_without_subcommand_shows_help
# ---------------------------------------------------------------------------


class TestCliWithoutSubcommandShowsHelp:
    def test_cli_without_subcommand_shows_help(self) -> None:
        """Invoking the CLI without a subcommand should show help text."""
        from amplifier_ipc.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, [])

        # Should show help - either exit code 0 with help text or non-zero
        # The key requirement is that it shows usage/help info
        assert (
            "usage" in result.output.lower()
            or "help" in result.output.lower()
            or "--help" in result.output
        )


# ---------------------------------------------------------------------------
# Test 5: test_version_command
# ---------------------------------------------------------------------------


class TestVersionCommand:
    def test_version_command(self) -> None:
        """The version command should output something containing 'amplifier-ipc-cli'."""
        from amplifier_ipc.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["version"])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}"
        )
        assert "amplifier-ipc-cli" in result.output


# ---------------------------------------------------------------------------
# Test 6: test_run_with_session_flag_passes_session_id
# ---------------------------------------------------------------------------


class TestRunWithSessionFlag:
    def test_run_with_session_flag_passes_session_id(self) -> None:
        """run --agent foundation --session abc123 'hello' passes session_id to host.

        After launch_session, _run_agent must call host.set_resume_session_id(session)
        when the --session flag is provided.
        """
        from amplifier_ipc.cli.main import cli

        runner = CliRunner()

        # Create a mock host with set_resume_session_id tracked
        mock_host = MagicMock()
        mock_host.set_resume_session_id = MagicMock()

        # Mock host.run as an async generator that yields no events
        async def mock_run(message: str):  # type: ignore[return]
            return
            yield  # makes this an async generator

        mock_host.run = mock_run

        with patch(
            "amplifier_ipc.cli.commands.run.launch_session", new_callable=AsyncMock
        ) as mock_launch:
            with patch("amplifier_ipc.cli.commands.run.KeyManager") as mock_km:
                mock_launch.return_value = mock_host
                mock_km.return_value.load_keys = MagicMock()
                result = runner.invoke(
                    cli,
                    ["run", "--agent", "foundation", "--session", "abc123", "hello"],
                )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}"
        )
        mock_host.set_resume_session_id.assert_called_once_with("abc123")
