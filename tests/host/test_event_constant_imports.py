"""Tests that host.py imports the required event constants from amplifier_ipc_protocol.events."""

from __future__ import annotations

import amplifier_ipc.host.host as host_module


def test_host_imports_cancel_completed() -> None:
    """CANCEL_COMPLETED event constant must be imported in host.py."""
    assert hasattr(host_module, "CANCEL_COMPLETED"), (
        "CANCEL_COMPLETED is not imported in host.py"
    )


def test_host_imports_cancel_requested() -> None:
    """CANCEL_REQUESTED event constant must be imported in host.py."""
    assert hasattr(host_module, "CANCEL_REQUESTED"), (
        "CANCEL_REQUESTED is not imported in host.py"
    )


def test_host_imports_session_fork() -> None:
    """SESSION_FORK event constant must be imported in host.py."""
    assert hasattr(host_module, "SESSION_FORK"), (
        "SESSION_FORK is not imported in host.py"
    )


def test_host_imports_session_resume() -> None:
    """SESSION_RESUME event constant must be imported in host.py."""
    assert hasattr(host_module, "SESSION_RESUME"), (
        "SESSION_RESUME is not imported in host.py"
    )


def test_host_imports_session_end_and_start() -> None:
    """SESSION_END and SESSION_START must remain imported in host.py."""
    assert hasattr(host_module, "SESSION_END"), "SESSION_END is not imported in host.py"
    assert hasattr(host_module, "SESSION_START"), (
        "SESSION_START is not imported in host.py"
    )


def test_all_six_event_constants_imported() -> None:
    """All six event constants must be importable from the host module."""
    expected = {
        "CANCEL_COMPLETED",
        "CANCEL_REQUESTED",
        "SESSION_END",
        "SESSION_FORK",
        "SESSION_RESUME",
        "SESSION_START",
    }
    for constant in expected:
        assert hasattr(host_module, constant), f"{constant} is not imported in host.py"
