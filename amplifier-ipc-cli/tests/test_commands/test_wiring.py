"""Tests for command wiring in main.py and new command modules.

Verifies that all expected commands appear in --help output and that each
new command module (provider, routing, reset) is correctly structured.
"""

from __future__ import annotations

from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_cli():
    """Import and return the cli group."""
    from amplifier_ipc_cli.main import cli

    return cli


# ---------------------------------------------------------------------------
# Tests: all expected commands appear in top-level --help
# ---------------------------------------------------------------------------


class TestTopLevelHelpListsAllCommands:
    """The top-level CLI --help must list every expected command."""

    EXPECTED_COMMANDS = [
        "run",
        "version",
        "discover",
        "register",
        "install",
        "update",
        "session",
        "provider",
        "routing",
        "reset",
    ]

    def test_help_lists_run(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["--help"])
        assert result.exit_code == 0
        assert "run" in result.output

    def test_help_lists_version(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["--help"])
        assert result.exit_code == 0
        assert "version" in result.output

    def test_help_lists_discover(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["--help"])
        assert result.exit_code == 0
        assert "discover" in result.output

    def test_help_lists_register(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["--help"])
        assert result.exit_code == 0
        assert "register" in result.output

    def test_help_lists_install(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["--help"])
        assert result.exit_code == 0
        assert "install" in result.output

    def test_help_lists_update(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["--help"])
        assert result.exit_code == 0
        assert "update" in result.output

    def test_help_lists_session(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["--help"])
        assert result.exit_code == 0
        assert "session" in result.output

    def test_help_lists_provider(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["--help"])
        assert result.exit_code == 0
        assert "provider" in result.output

    def test_help_lists_routing(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["--help"])
        assert result.exit_code == 0
        assert "routing" in result.output

    def test_help_lists_reset(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["--help"])
        assert result.exit_code == 0
        assert "reset" in result.output

    def test_help_lists_allowed_dirs(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["--help"])
        assert result.exit_code == 0
        assert "allowed-dirs" in result.output

    def test_help_lists_denied_dirs(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["--help"])
        assert result.exit_code == 0
        assert "denied-dirs" in result.output

    def test_help_lists_notify(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["--help"])
        assert result.exit_code == 0
        assert "notify" in result.output


# ---------------------------------------------------------------------------
# Tests: provider command --help
# ---------------------------------------------------------------------------


class TestProviderCommandHelp:
    """provider group must expose list, set-key, and use subcommands."""

    def test_provider_help_exits_zero(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["provider", "--help"])
        assert result.exit_code == 0

    def test_provider_help_lists_list(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["provider", "--help"])
        assert "list" in result.output

    def test_provider_help_lists_set_key(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["provider", "--help"])
        assert "set-key" in result.output

    def test_provider_help_lists_use(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["provider", "--help"])
        assert "use" in result.output

    def test_provider_list_help_exits_zero(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["provider", "list", "--help"])
        assert result.exit_code == 0

    def test_provider_set_key_help_exits_zero(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["provider", "set-key", "--help"])
        assert result.exit_code == 0

    def test_provider_use_help_exits_zero(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["provider", "use", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Tests: routing command --help
# ---------------------------------------------------------------------------


class TestRoutingCommandHelp:
    """routing group must expose list, show, and use subcommands."""

    def test_routing_help_exits_zero(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["routing", "--help"])
        assert result.exit_code == 0

    def test_routing_help_lists_list(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["routing", "--help"])
        assert "list" in result.output

    def test_routing_help_lists_show(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["routing", "--help"])
        assert "show" in result.output

    def test_routing_help_lists_use(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["routing", "--help"])
        assert "use" in result.output

    def test_routing_list_help_exits_zero(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["routing", "list", "--help"])
        assert result.exit_code == 0

    def test_routing_show_help_exits_zero(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["routing", "show", "--help"])
        assert result.exit_code == 0

    def test_routing_use_help_exits_zero(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["routing", "use", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Tests: reset command --help
# ---------------------------------------------------------------------------


class TestResetCommandHelp:
    """reset command must expose --remove and --dry-run options."""

    def test_reset_help_exits_zero(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["reset", "--help"])
        assert result.exit_code == 0

    def test_reset_help_lists_remove_option(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["reset", "--help"])
        assert "--remove" in result.output

    def test_reset_help_lists_dry_run_option(self):
        runner = CliRunner()
        result = runner.invoke(_get_cli(), ["reset", "--help"])
        assert "--dry-run" in result.output


# ---------------------------------------------------------------------------
# Tests: provider module importable and has correct name
# ---------------------------------------------------------------------------


class TestProviderModule:
    """provider_group is importable with name='provider'."""

    def test_provider_group_importable(self):
        from amplifier_ipc_cli.commands.provider import provider_group

        assert provider_group is not None

    def test_provider_group_name(self):
        from amplifier_ipc_cli.commands.provider import provider_group

        assert provider_group.name == "provider"


# ---------------------------------------------------------------------------
# Tests: routing module importable and has correct name
# ---------------------------------------------------------------------------


class TestRoutingModule:
    """routing_group is importable with name='routing'."""

    def test_routing_group_importable(self):
        from amplifier_ipc_cli.commands.routing import routing_group

        assert routing_group is not None

    def test_routing_group_name(self):
        from amplifier_ipc_cli.commands.routing import routing_group

        assert routing_group.name == "routing"


# ---------------------------------------------------------------------------
# Tests: reset module importable and has correct name
# ---------------------------------------------------------------------------


class TestResetModule:
    """reset_cmd is importable with name='reset'."""

    def test_reset_cmd_importable(self):
        from amplifier_ipc_cli.commands.reset import reset_cmd

        assert reset_cmd is not None

    def test_reset_cmd_name(self):
        from amplifier_ipc_cli.commands.reset import reset_cmd

        assert reset_cmd.name == "reset"


# ---------------------------------------------------------------------------
# Tests: reset helper functions
# ---------------------------------------------------------------------------


class TestResetHelpers:
    """_get_target_paths and _remove_path helpers work correctly."""

    def test_get_target_paths_environments(self, tmp_path):
        from amplifier_ipc_cli.commands.reset import _get_target_paths

        paths = _get_target_paths("environments", tmp_path)
        assert len(paths) >= 1
        assert any("environments" in str(p) for p in paths)

    def test_get_target_paths_definitions(self, tmp_path):
        from amplifier_ipc_cli.commands.reset import _get_target_paths

        paths = _get_target_paths("definitions", tmp_path)
        assert len(paths) >= 1
        assert any("definitions" in str(p) for p in paths)

    def test_get_target_paths_sessions(self, tmp_path):
        from amplifier_ipc_cli.commands.reset import _get_target_paths

        paths = _get_target_paths("sessions", tmp_path)
        assert len(paths) >= 1
        assert any("sessions" in str(p) for p in paths)

    def test_get_target_paths_keys(self, tmp_path):
        from amplifier_ipc_cli.commands.reset import _get_target_paths

        paths = _get_target_paths("keys", tmp_path)
        assert len(paths) >= 1
        assert any("keys" in str(p) for p in paths)

    def test_get_target_paths_all_returns_multiple(self, tmp_path):
        from amplifier_ipc_cli.commands.reset import _get_target_paths

        paths = _get_target_paths("all", tmp_path)
        # "all" must return paths for all categories
        assert len(paths) > 1

    def test_remove_path_removes_file(self, tmp_path):
        from amplifier_ipc_cli.commands.reset import _remove_path

        f = tmp_path / "test.txt"
        f.write_text("hello")
        assert f.exists()
        _remove_path(f)
        assert not f.exists()

    def test_remove_path_removes_directory(self, tmp_path):
        from amplifier_ipc_cli.commands.reset import _remove_path

        d = tmp_path / "subdir"
        d.mkdir()
        (d / "file.txt").write_text("hello")
        assert d.exists()
        _remove_path(d)
        assert not d.exists()

    def test_remove_path_nonexistent_is_noop(self, tmp_path):
        from amplifier_ipc_cli.commands.reset import _remove_path

        nonexistent = tmp_path / "does_not_exist"
        # Should not raise
        _remove_path(nonexistent)


# ---------------------------------------------------------------------------
# Tests: reset dry-run behaviour
# ---------------------------------------------------------------------------


class TestResetDryRun:
    """reset --dry-run must not actually delete anything."""

    def test_dry_run_does_not_delete(self, tmp_path):
        from amplifier_ipc_cli.commands.reset import reset_cmd

        amp_dir = tmp_path / ".amplifier"
        sessions_dir = amp_dir / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "my_session.txt").write_text("data")

        runner = CliRunner()
        runner.invoke(
            reset_cmd,
            ["--remove", "sessions", "--dry-run"],
            catch_exceptions=False,
            env={"HOME": str(tmp_path)},
        )
        # The file should still exist since it's a dry run
        assert sessions_dir.exists()
