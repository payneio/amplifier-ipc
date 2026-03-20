"""Tests for capability registry module."""

from __future__ import annotations

from amplifier_ipc_host.registry import CapabilityRegistry


# ---------------------------------------------------------------------------
# Fake describe helpers
# ---------------------------------------------------------------------------


def _foundation_describe() -> dict:
    return {
        "tools": [
            {"name": "bash", "description": "Run bash commands"},
            {"name": "read_file", "description": "Read a file"},
        ],
        "hooks": [
            {"name": "approval", "event": "tool:pre", "priority": 10},
            {"name": "logging", "event": "tool:post", "priority": 5},
        ],
        "orchestrators": [
            {"name": "streaming"},
        ],
        "context_managers": [
            {"name": "simple"},
        ],
        "providers": [],
        "content": ["context/foundation.md", "context/tools.md"],
    }


def _providers_describe() -> dict:
    return {
        "tools": [],
        "hooks": [],
        "orchestrators": [],
        "context_managers": [],
        "providers": [
            {"name": "anthropic"},
            {"name": "openai"},
        ],
        "content": [],
    }


def _modes_describe() -> dict:
    return {
        "tools": [
            {"name": "mode", "description": "Switch modes"},
        ],
        "hooks": [
            {"name": "mode_hook", "event": "tool:pre", "priority": 20},
        ],
        "orchestrators": [],
        "context_managers": [],
        "providers": [],
        "content": ["context/modes.md"],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_register_and_lookup_tool() -> None:
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())

    assert registry.get_tool_service("bash") == "foundation"
    assert registry.get_tool_service("read_file") == "foundation"


def test_lookup_unknown_tool() -> None:
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())

    assert registry.get_tool_service("nonexistent") is None


def test_register_and_lookup_hook_services() -> None:
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())
    registry.register("modes", _modes_describe())

    entries = registry.get_hook_services("tool:pre")

    assert len(entries) == 2
    # Sorted ascending by priority: 10 (approval/foundation), 20 (mode_hook/modes)
    assert entries[0] == {
        "service_key": "foundation",
        "hook_name": "approval",
        "event": "tool:pre",
        "priority": 10,
    }
    assert entries[1] == {
        "service_key": "modes",
        "hook_name": "mode_hook",
        "event": "tool:pre",
        "priority": 20,
    }


def test_lookup_hooks_unknown_event() -> None:
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())

    assert registry.get_hook_services("unknown:event") == []


def test_register_and_lookup_orchestrator() -> None:
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())

    assert registry.get_orchestrator_service("streaming") == "foundation"


def test_register_and_lookup_context_manager() -> None:
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())

    assert registry.get_context_manager_service("simple") == "foundation"


def test_register_and_lookup_provider() -> None:
    registry = CapabilityRegistry()
    registry.register("providers", _providers_describe())

    assert registry.get_provider_service("anthropic") == "providers"
    assert registry.get_provider_service("openai") == "providers"


def test_get_all_tool_specs() -> None:
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())
    registry.register("modes", _modes_describe())

    specs = registry.get_all_tool_specs()

    names = [s["name"] for s in specs]
    assert "bash" in names
    assert "read_file" in names
    assert "mode" in names
    assert len(specs) == 3


def test_get_all_hook_descriptors() -> None:
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())
    registry.register("modes", _modes_describe())

    descriptors = registry.get_all_hook_descriptors()

    names = [d["name"] for d in descriptors]
    assert "approval" in names
    assert "logging" in names
    assert "mode_hook" in names
    assert len(descriptors) == 3


def test_get_content_services() -> None:
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())
    registry.register("modes", _modes_describe())

    content = registry.get_content_services()

    assert content["foundation"] == ["context/foundation.md", "context/tools.md"]
    assert content["modes"] == ["context/modes.md"]


def test_lookup_unknown_provider() -> None:
    registry = CapabilityRegistry()
    registry.register("providers", _providers_describe())

    assert registry.get_provider_service("unknown-provider") is None
    assert registry.get_orchestrator_service("unknown-orch") is None
    assert registry.get_context_manager_service("unknown-ctx") is None
