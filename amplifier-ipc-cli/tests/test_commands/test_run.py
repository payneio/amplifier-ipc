"""Tests for commands/run.py - the run command and CLI wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Test 1: test_run_no_agent_shows_error
# ---------------------------------------------------------------------------


class TestRunNoAgentShowsError:
    def test_run_no_agent_shows_error(self) -> None:
        """Running 'run' without --agent should show an error."""
        from amplifier_ipc_cli.main import cli

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
        from amplifier_ipc_cli.main import cli

        runner = CliRunner()

        with patch(
            "amplifier_ipc_cli.commands.run._run_agent", new_callable=AsyncMock
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
        from amplifier_ipc_cli.main import cli

        runner = CliRunner()

        with patch(
            "amplifier_ipc_cli.commands.run._run_agent", new_callable=AsyncMock
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
        from amplifier_ipc_cli.main import cli

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
        from amplifier_ipc_cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["version"])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}"
        )
        assert "amplifier-ipc-cli" in result.output
