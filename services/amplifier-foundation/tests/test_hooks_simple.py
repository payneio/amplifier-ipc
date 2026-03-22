"""Tests for simple hooks: deprecation, progress_monitor, redaction, todo_display, todo_reminder.

Verifies:
1. All 5 hooks are discovered by scan_package.
2. All discovered hooks have a non-empty events attribute.
3. TodoReminderHook.handle() returns a valid HookResult.
"""

from __future__ import annotations

import pytest

from amplifier_ipc.protocol.discovery import scan_package
from amplifier_ipc.protocol.models import HookAction, HookResult


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
# Test 1: all 5 hooks discovered
# ---------------------------------------------------------------------------

EXPECTED_HOOK_NAMES = {
    "DeprecationHook",
    "ProgressMonitorHook",
    "RedactionHook",
    "TodoDisplayHook",
    "TodoReminderHook",
}


def test_simple_hooks_discovered(hooks_by_name: dict) -> None:
    """All 5 simple hooks must be found by scan_package('amplifier_foundation').

    Ensures each hook file exists in hooks/ directory, is decorated with
    @hook(...), and can be instantiated with no arguments.
    """
    discovered = set(hooks_by_name.keys())
    missing = EXPECTED_HOOK_NAMES - discovered
    assert not missing, (
        f"The following hooks were not discovered by scan_package: {missing}. "
        "Ensure each hook file is in hooks/ directory and decorated with @hook(events=[...])."
    )


# ---------------------------------------------------------------------------
# Test 2: all hooks have non-empty events attribute
# ---------------------------------------------------------------------------


def test_hooks_have_events_attribute(hooks_by_name: dict) -> None:
    """All 5 simple hooks must have a non-empty 'events' attribute.

    The @hook(events=[...]) decorator sets __amplifier_hook_events__ on the
    class, and the instance should also expose 'events' as a class attribute.
    """
    for name in EXPECTED_HOOK_NAMES:
        hook = hooks_by_name.get(name)
        assert hook is not None, f"{name} not found in discovered hooks"

        # Check events attribute
        events = getattr(hook, "events", None)
        assert events is not None, (
            f"{name} is missing 'events' attribute. "
            "Set events = [...] as a class attribute."
        )
        assert len(events) > 0, (
            f"{name}.events is empty. At least one event must be subscribed to."
        )


# ---------------------------------------------------------------------------
# Test 3: TodoReminderHook.handle() returns valid HookResult
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_todo_reminder_handle_returns_hook_result(hooks_by_name: dict) -> None:
    """TodoReminderHook.handle() must return a HookResult with a valid HookAction.

    Since todo_display and todo_reminder stub out session access, handle()
    should return HookResult(action=HookAction.CONTINUE) as a no-op stub.
    """
    hook = hooks_by_name.get("TodoReminderHook")
    assert hook is not None, "TodoReminderHook not found in discovered hooks"

    result = await hook.handle("provider:request", {"session_id": "test-123"})

    assert isinstance(result, HookResult), (
        f"TodoReminderHook.handle() must return HookResult, got {type(result)}"
    )
    assert isinstance(result.action, HookAction), (
        f"HookResult.action must be a HookAction enum, got {type(result.action)}"
    )
