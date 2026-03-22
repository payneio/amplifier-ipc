"""Tests for amplifier_ipc.cli package imports and version."""

import importlib


def test_package_imports() -> None:
    """Verify amplifier_ipc.cli package can be imported."""
    pkg = importlib.import_module("amplifier_ipc.cli")
    assert pkg is not None


def test_package_version() -> None:
    """Verify __version__ is set to '0.1.0'."""
    import amplifier_ipc.cli

    assert amplifier_ipc.cli.__version__ == "0.1.0"


def test_main_module_imports() -> None:
    """Verify amplifier_ipc.cli.main can be imported."""
    mod = importlib.import_module("amplifier_ipc.cli.main")
    assert mod is not None


def test_cli_group_exists() -> None:
    """Verify cli Click group is defined in main module."""
    from amplifier_ipc.cli.main import cli

    assert cli is not None


def test_main_entry_point_exists() -> None:
    """Verify main() entry point function exists."""
    from amplifier_ipc.cli.main import main

    assert callable(main)


def test_cli_shows_help(tmp_path: object) -> None:
    """Verify cli group shows help when invoked without subcommand."""
    from click.testing import CliRunner

    from amplifier_ipc.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output
