"""Final cleanup: verify exact component counts per acceptance criteria.

Acceptance criteria:
- orchestrator: 1 (streaming)
- context_manager: 1 (simple)
- hook: exactly 12 (approval, deprecation, logging, progress_monitor, redaction,
        routing, session_naming, shell, status_context, streaming_ui, todo_display,
        todo_reminder)
- tool: >= 14 (bash, todo, web_search, web_fetch, read_file, write_file, edit_file,
         grep, glob, delegate, task, mcp, recipes, apply_patch, ...)
- content: >= 50 files

Uses scan_package and scan_content (the same discovery path the IPC server uses)
to verify the live component inventory.
"""

from __future__ import annotations

import pytest

from amplifier_ipc_protocol.discovery import scan_package, scan_content


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def components() -> dict:
    """Discover all components via scan_package."""
    return scan_package("amplifier_foundation")


@pytest.fixture(scope="module")
def content_paths() -> list[str]:
    """Discover all content files via scan_content."""
    return scan_content("amplifier_foundation")


# ---------------------------------------------------------------------------
# Orchestrator count
# ---------------------------------------------------------------------------


def test_orchestrator_count(components: dict) -> None:
    """Must have exactly 1 orchestrator: streaming."""
    orchestrators = components.get("orchestrator", [])
    names = [type(o).__name__ for o in orchestrators]
    assert len(orchestrators) == 1, (
        f"Expected 1 orchestrator, got {len(orchestrators)}: {names}"
    )
    assert any("Streaming" in n or "streaming" in n.lower() for n in names), (
        f"Expected 'streaming' orchestrator, found: {names}"
    )


# ---------------------------------------------------------------------------
# Context manager count
# ---------------------------------------------------------------------------


def test_context_manager_count(components: dict) -> None:
    """Must have exactly 1 context manager: simple."""
    context_managers = components.get("context_manager", [])
    names = [type(cm).__name__ for cm in context_managers]
    assert len(context_managers) == 1, (
        f"Expected 1 context_manager, got {len(context_managers)}: {names}"
    )
    assert any("Simple" in n or "simple" in n.lower() for n in names), (
        f"Expected 'simple' context_manager, found: {names}"
    )


# ---------------------------------------------------------------------------
# Hook count and names
# ---------------------------------------------------------------------------

EXPECTED_HOOKS = {
    "approval",
    "deprecation",
    "logging",
    "progress_monitor",
    "redaction",
    "routing",
    "session_naming",
    "shell",
    "status_context",
    "streaming_ui",
    "todo_display",
    "todo_reminder",
}


def test_hook_count(components: dict) -> None:
    """Must have exactly 12 hooks."""
    hooks = components.get("hook", [])
    names = [type(h).__name__ for h in hooks]
    assert len(hooks) == 12, f"Expected exactly 12 hooks, got {len(hooks)}: {names}"


def test_hook_names(components: dict) -> None:
    """All 12 required hooks must be present (by IPC describe name attribute)."""
    hooks = components.get("hook", [])

    # Hooks expose a `name` attribute (set by the @hook decorator or as class attr)
    discovered_names: set[str] = set()
    for h in hooks:
        name = getattr(h, "name", None)
        if name:
            discovered_names.add(name)

    missing = EXPECTED_HOOKS - discovered_names
    assert not missing, (
        f"Missing hooks: {sorted(missing)}. "
        f"Discovered hook names: {sorted(discovered_names)}"
    )


# ---------------------------------------------------------------------------
# Tool count and required set
# ---------------------------------------------------------------------------

REQUIRED_TOOLS = {
    "bash",
    "todo",
    "web_search",
    "web_fetch",
    "read_file",
    "write_file",
    "edit_file",
    "grep",
    "glob",
    "delegate",
    "task",
    "mcp",
    "recipes",
    "apply_patch",
}


def test_tool_count(components: dict) -> None:
    """Must have >= 14 tools."""
    tools = components.get("tool", [])
    names = [type(t).__name__ for t in tools]
    assert len(tools) >= 14, f"Expected >= 14 tools, got {len(tools)}: {names}"


def test_required_tools_present(components: dict) -> None:
    """All 14 required tools must be discoverable (by IPC name attribute)."""
    tools = components.get("tool", [])
    discovered_names: set[str] = set()
    for t in tools:
        name = getattr(t, "name", None)
        if name:
            discovered_names.add(name)

    missing = REQUIRED_TOOLS - discovered_names
    assert not missing, (
        f"Missing required tools: {sorted(missing)}. "
        f"Discovered tool names: {sorted(discovered_names)}"
    )


# ---------------------------------------------------------------------------
# Content file count
# ---------------------------------------------------------------------------


def test_content_file_count(content_paths: list[str]) -> None:
    """Must have >= 50 content files."""
    assert len(content_paths) >= 50, (
        f"Expected >= 50 content files, got {len(content_paths)}"
    )


def test_content_has_agents(content_paths: list[str]) -> None:
    """Content must include agent definition files."""
    agents = [p for p in content_paths if p.startswith("agents/")]
    assert len(agents) >= 10, f"Expected >= 10 agent files, got {len(agents)}: {agents}"


def test_content_has_behaviors(content_paths: list[str]) -> None:
    """Content must include behavior YAML files."""
    behaviors = [p for p in content_paths if p.startswith("behaviors/")]
    assert len(behaviors) >= 5, (
        f"Expected >= 5 behavior files, got {len(behaviors)}: {behaviors}"
    )


def test_content_has_context(content_paths: list[str]) -> None:
    """Content must include context/philosophy files."""
    context = [p for p in content_paths if p.startswith("context/")]
    assert len(context) >= 10, (
        f"Expected >= 10 context files, got {len(context)}: {context}"
    )
