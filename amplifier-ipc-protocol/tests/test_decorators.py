"""Tests for component discovery decorators."""

from __future__ import annotations

from amplifier_ipc_protocol.decorators import (
    context_manager,
    hook,
    orchestrator,
    provider,
    tool,
)


# ---------------------------------------------------------------------------
# @tool decorator tests
# ---------------------------------------------------------------------------


def test_tool_decorator_sets_metadata():
    """@tool sets __amplifier_component__ to 'tool'."""

    @tool
    class MyTool:
        pass

    assert MyTool.__amplifier_component__ == "tool"  # type: ignore[attr-defined]


def test_tool_decorator_preserves_class():
    """@tool preserves class attributes and instantiation works."""

    @tool
    class MyTool:
        name = "my_tool"

        def greet(self):
            return "hello"

    assert MyTool.name == "my_tool"
    instance = MyTool()
    assert instance.greet() == "hello"


# ---------------------------------------------------------------------------
# @hook decorator tests
# ---------------------------------------------------------------------------


def test_hook_decorator_sets_metadata():
    """@hook sets __amplifier_component__, __amplifier_hook_events__, __amplifier_hook_priority__."""

    @hook(events=["pre_call", "post_call"], priority=10)
    class MyHook:
        pass

    assert MyHook.__amplifier_component__ == "hook"  # type: ignore[attr-defined]
    assert MyHook.__amplifier_hook_events__ == ["pre_call", "post_call"]  # type: ignore[attr-defined]
    assert MyHook.__amplifier_hook_priority__ == 10  # type: ignore[attr-defined]


def test_hook_decorator_default_priority():
    """@hook priority defaults to 0 when not specified."""

    @hook(events=["on_start"])
    class MyHook:
        pass

    assert MyHook.__amplifier_hook_priority__ == 0  # type: ignore[attr-defined]


def test_hook_decorator_preserves_class():
    """@hook preserves class attributes."""

    @hook(events=["on_event"])
    class MyHook:
        name = "my_hook"

    assert MyHook.name == "my_hook"
    instance = MyHook()
    assert isinstance(instance, MyHook)


# ---------------------------------------------------------------------------
# @orchestrator decorator tests
# ---------------------------------------------------------------------------


def test_orchestrator_decorator_sets_metadata():
    """@orchestrator sets __amplifier_component__ to 'orchestrator'."""

    @orchestrator
    class MyOrchestrator:
        pass

    assert MyOrchestrator.__amplifier_component__ == "orchestrator"  # type: ignore[attr-defined]


def test_orchestrator_decorator_preserves_class():
    """@orchestrator preserves class name attribute."""

    @orchestrator
    class MyOrchestrator:
        name = "my_orchestrator"

    assert MyOrchestrator.name == "my_orchestrator"


# ---------------------------------------------------------------------------
# @context_manager decorator tests
# ---------------------------------------------------------------------------


def test_context_manager_decorator_sets_metadata():
    """@context_manager sets __amplifier_component__ to 'context_manager'."""

    @context_manager
    class MyContextManager:
        pass

    assert MyContextManager.__amplifier_component__ == "context_manager"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# @provider decorator tests
# ---------------------------------------------------------------------------


def test_provider_decorator_sets_metadata():
    """@provider sets __amplifier_component__ to 'provider'."""

    @provider
    class MyProvider:
        pass

    assert MyProvider.__amplifier_component__ == "provider"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Identity (same object) tests
# ---------------------------------------------------------------------------


def test_decorated_class_is_same_object():
    """@tool returns the SAME class object (identity check)."""

    class Original:
        pass

    decorated = tool(Original)
    assert decorated is Original


def test_hook_decorated_class_is_same_object():
    """@hook returns the SAME class object (identity check)."""

    class Original:
        pass

    decorated = hook(events=["on_test"])(Original)
    assert decorated is Original
