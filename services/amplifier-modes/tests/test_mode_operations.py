"""Tests for ModeHooks accessor methods: set_active_mode, clear_active_mode, get_active_mode."""

from amplifier_modes.hooks.mode import ModeDefinition, ModeHooks


def make_mode(name: str = "test-mode") -> ModeDefinition:
    """Create a minimal ModeDefinition for testing."""
    return ModeDefinition(name=name, description="Test mode")


def test_get_active_mode_returns_none_by_default() -> None:
    """Fresh ModeHooks has no active mode."""
    hooks = ModeHooks()
    assert hooks.get_active_mode() is None


def test_set_active_mode_stores_mode() -> None:
    """set_active_mode stores mode retrievable via get_active_mode."""
    hooks = ModeHooks()
    mode = make_mode("plan")
    hooks.set_active_mode(mode)
    assert hooks.get_active_mode() is mode


def test_set_active_mode_clears_warned_tools() -> None:
    """set_active_mode resets _warned_tools set."""
    hooks = ModeHooks()
    # Populate _warned_tools directly to simulate prior state
    hooks._warned_tools.add("plan:bash")
    hooks._warned_tools.add("plan:write_file")
    mode = make_mode("plan")
    hooks.set_active_mode(mode)
    assert hooks._warned_tools == set()


def test_clear_active_mode_removes_mode() -> None:
    """clear_active_mode sets active mode back to None."""
    hooks = ModeHooks()
    mode = make_mode("debug")
    hooks.set_active_mode(mode)
    hooks.clear_active_mode()
    assert hooks.get_active_mode() is None


def test_clear_active_mode_clears_warned_tools() -> None:
    """clear_active_mode resets _warned_tools set."""
    hooks = ModeHooks()
    hooks._warned_tools.add("debug:bash")
    hooks.clear_active_mode()
    assert hooks._warned_tools == set()


def test_clear_active_mode_is_idempotent() -> None:
    """Clearing when nothing active does not raise."""
    hooks = ModeHooks()
    # Should not raise even with no active mode
    hooks.clear_active_mode()
    hooks.clear_active_mode()
    assert hooks.get_active_mode() is None
