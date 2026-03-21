"""Tests for remaining hooks: approval, logging, routing, session_naming, shell,
status_context, streaming_ui.

Verifies:
1. All 7 hooks are discovered by scan_package.
2. All discovered hooks have a callable handle() method.
"""

from __future__ import annotations

import pytest

from amplifier_ipc_protocol.discovery import scan_package


@pytest.fixture(scope="module")
def all_hooks() -> list:
    """Discover all hooks via scan_package."""
    components = scan_package("amplifier_foundation")
    return components.get("hook", [])


@pytest.fixture(scope="module")
def hooks_by_name(all_hooks) -> dict:
    """Map hook instances by class name for convenient lookup."""
    return {type(h).__name__: h for h in all_hooks}


# ---------------------------------------------------------------------------
# Expected hook class names (one per hook module)
# ---------------------------------------------------------------------------

EXPECTED_REMAINING_HOOK_NAMES = {
    "ApprovalHook",
    "LoggingHook",
    "RoutingHook",
    "SessionNamingHook",
    "ShellHook",
    "StatusContextHook",
    "StreamingUIHook",
}


# ---------------------------------------------------------------------------
# Test 1: all 7 remaining hooks discovered
# ---------------------------------------------------------------------------


def test_all_remaining_hooks_discovered(hooks_by_name: dict) -> None:
    """All 7 remaining hooks must be found by scan_package('amplifier_foundation').

    Ensures each hook file exists in hooks/ directory, is decorated with
    @hook(...), and can be instantiated with no arguments.
    """
    discovered = set(hooks_by_name.keys())
    missing = EXPECTED_REMAINING_HOOK_NAMES - discovered
    assert not missing, (
        f"The following hooks were not discovered by scan_package: {missing}. "
        "Ensure each hook file is in hooks/ directory and decorated with @hook(events=[...])."
    )


# ---------------------------------------------------------------------------
# Test 2: all hooks have callable handle() method
# ---------------------------------------------------------------------------


def test_all_hooks_have_handle_method(hooks_by_name: dict) -> None:
    """All 7 remaining hooks must have a callable handle() method."""
    for name in EXPECTED_REMAINING_HOOK_NAMES:
        hook = hooks_by_name.get(name)
        assert hook is not None, f"{name} not found in discovered hooks"

        handle = getattr(hook, "handle", None)
        assert handle is not None, (
            f"{name} is missing 'handle' method. "
            "Add an async handle(event, data) method."
        )
        assert callable(handle), f"{name}.handle is not callable."
