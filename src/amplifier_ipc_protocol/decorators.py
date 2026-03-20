"""Component discovery decorators for Amplifier IPC.

Decorators mark classes as IPC components by attaching metadata attributes.
They do NOT change class behavior — they only add ``__amplifier_component__``
(and hook-specific attributes) so the generic Server can discover them at startup.
"""

from __future__ import annotations

from collections.abc import Callable


def _mark_component(cls: type, component_type: str) -> type:
    """Internal helper — sets __amplifier_component__ on the class and returns it."""
    cls.__amplifier_component__ = component_type  # type: ignore[attr-defined]
    return cls


def tool(cls: type) -> type:
    """Mark a class as a tool component."""
    return _mark_component(cls, "tool")


def hook(events: list[str], priority: int = 0) -> Callable[[type], type]:
    """Decorator factory — mark a class as a hook component with event subscriptions."""

    def decorator(cls: type) -> type:
        _mark_component(cls, "hook")
        cls.__amplifier_hook_events__ = events  # type: ignore[attr-defined]
        cls.__amplifier_hook_priority__ = priority  # type: ignore[attr-defined]
        return cls

    return decorator


def orchestrator(cls: type) -> type:
    """Mark a class as an orchestrator component."""
    return _mark_component(cls, "orchestrator")


def context_manager(cls: type) -> type:
    """Mark a class as a context_manager component."""
    return _mark_component(cls, "context_manager")


def provider(cls: type) -> type:
    """Mark a class as a provider component."""
    return _mark_component(cls, "provider")
