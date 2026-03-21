"""Verify all copied/adapted modules import cleanly with amplifier_ipc_cli namespace."""

from __future__ import annotations


def test_console_imports() -> None:
    """console.py imports cleanly (zero amplifier_lite imports)."""
    import amplifier_ipc_cli.console as m

    assert hasattr(m, "console")
    assert hasattr(m, "Markdown")
    assert hasattr(m, "LeftAlignedHeading")


def test_key_manager_imports() -> None:
    """key_manager.py imports cleanly (pure stdlib)."""
    import amplifier_ipc_cli.key_manager as m

    assert hasattr(m, "KeyManager")


def test_paths_imports() -> None:
    """paths.py imports cleanly (pure pathlib)."""
    import amplifier_ipc_cli.paths as m

    assert hasattr(m, "get_project_slug")
    assert hasattr(m, "get_session_dir")


def test_settings_imports() -> None:
    """settings.py imports cleanly (yaml + pathlib)."""
    import amplifier_ipc_cli.settings as m

    assert hasattr(m, "AppSettings")
    assert hasattr(m, "get_settings")


def test_ui_init_imports() -> None:
    """ui/__init__.py exports CLIDisplaySystem, format_throttle_warning, render_message."""
    import amplifier_ipc_cli.ui as m

    assert hasattr(m, "CLIDisplaySystem")
    assert hasattr(m, "format_throttle_warning")
    assert hasattr(m, "render_message")


def test_ui_display_imports() -> None:
    """ui/display.py imports cleanly (zero amplifier_lite imports)."""
    import amplifier_ipc_cli.ui.display as m

    assert hasattr(m, "CLIDisplaySystem")
    assert hasattr(m, "format_throttle_warning")


def test_ui_message_renderer_imports() -> None:
    """ui/message_renderer.py imports cleanly with amplifier_ipc_cli.console."""
    import amplifier_ipc_cli.ui.message_renderer as m

    assert hasattr(m, "render_message")


def test_ui_error_display_imports() -> None:
    """ui/error_display.py imports cleanly with display_error() function."""
    import amplifier_ipc_cli.ui.error_display as m

    assert hasattr(m, "display_error")
    assert callable(m.display_error)


def test_commands_init_imports() -> None:
    """commands/__init__.py imports cleanly (empty)."""
    import amplifier_ipc_cli.commands  # noqa: F401


def test_commands_notify_imports() -> None:
    """commands/notify.py exports notify_group."""
    import amplifier_ipc_cli.commands.notify as m

    assert hasattr(m, "notify_group")


def test_commands_allowed_dirs_imports() -> None:
    """commands/allowed_dirs.py exports allowed_dirs_group."""
    import amplifier_ipc_cli.commands.allowed_dirs as m

    assert hasattr(m, "allowed_dirs_group")


def test_commands_denied_dirs_imports() -> None:
    """commands/denied_dirs.py exports denied_dirs_group."""
    import amplifier_ipc_cli.commands.denied_dirs as m

    assert hasattr(m, "denied_dirs_group")


def test_commands_version_imports() -> None:
    """commands/version.py exports version command."""
    import amplifier_ipc_cli.commands.version as m

    assert hasattr(m, "version")


def test_no_amplifier_lite_cli_imports_in_console() -> None:
    """console.py has no amplifier_lite_cli imports."""
    import importlib

    spec = importlib.util.find_spec("amplifier_ipc_cli.console")
    assert spec is not None
    source = spec.origin
    assert source is not None
    content = open(source).read()
    assert "amplifier_lite_cli" not in content


def test_no_amplifier_lite_cli_imports_in_ui_message_renderer() -> None:
    """ui/message_renderer.py uses amplifier_ipc_cli.console, not amplifier_lite_cli."""
    import importlib

    spec = importlib.util.find_spec("amplifier_ipc_cli.ui.message_renderer")
    assert spec is not None
    source = spec.origin
    assert source is not None
    content = open(source).read()
    assert "amplifier_lite_cli" not in content
    assert "amplifier_ipc_cli.console" in content


def test_no_amplifier_lite_cli_imports_in_commands() -> None:
    """No command file imports from amplifier_lite_cli."""
    import importlib

    for mod_name in [
        "amplifier_ipc_cli.commands.notify",
        "amplifier_ipc_cli.commands.allowed_dirs",
        "amplifier_ipc_cli.commands.denied_dirs",
        "amplifier_ipc_cli.commands.version",
    ]:
        spec = importlib.util.find_spec(mod_name)
        assert spec is not None, f"Module {mod_name} not found"
        source = spec.origin
        assert source is not None
        content = open(source).read()
        assert "amplifier_lite_cli" not in content, (
            f"{mod_name} still imports from amplifier_lite_cli"
        )
