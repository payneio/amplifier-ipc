"""Tests for WebSearchTool, WebFetchTool, DelegateTool, TaskTool — verifies discovery and core behaviors."""

from __future__ import annotations

import asyncio

import pytest

from amplifier_ipc_protocol.discovery import scan_package


@pytest.fixture(scope="module")
def all_tools() -> dict:
    """Discover all tools via scan_package and return as name->instance dict."""
    components = scan_package("amplifier_foundation")
    return {getattr(t, "name", None): t for t in components.get("tool", [])}


def test_web_search_tool_discovered(all_tools: dict) -> None:
    """WebSearchTool must be found by scan_package under the 'tool' component type."""
    assert "web_search" in all_tools, (
        "WebSearchTool with name='web_search' not found by scan_package('amplifier_foundation'). "
        "Ensure tools/web.py exists and is decorated with @tool."
    )


def test_web_fetch_tool_discovered(all_tools: dict) -> None:
    """WebFetchTool must be found by scan_package under the 'tool' component type."""
    assert "web_fetch" in all_tools, (
        "WebFetchTool with name='web_fetch' not found by scan_package('amplifier_foundation'). "
        "Ensure tools/web.py exists and is decorated with @tool."
    )


def test_delegate_tool_discovered(all_tools: dict) -> None:
    """DelegateTool must be found by scan_package under the 'tool' component type."""
    assert "delegate" in all_tools, (
        "DelegateTool with name='delegate' not found by scan_package('amplifier_foundation'). "
        "Ensure tools/delegate.py exists and is decorated with @tool."
    )


def test_task_tool_discovered(all_tools: dict) -> None:
    """TaskTool must be found by scan_package under the 'tool' component type."""
    assert "task" in all_tools, (
        "TaskTool with name='task' not found by scan_package('amplifier_foundation'). "
        "Ensure tools/task.py exists and is decorated with @tool."
    )


def test_web_search_requires_query(all_tools: dict) -> None:
    """WebSearchTool returns error on empty input (missing query field)."""
    tool = all_tools.get("web_search")
    assert tool is not None, "web_search tool not found"

    result = asyncio.run(tool.execute({}))

    assert result.success is False, "Expected failure when query is missing"
    assert result.error is not None, "Expected error to be set when query is missing"


def test_delegate_stub_returns_not_implemented(all_tools: dict) -> None:
    """DelegateTool stub must return a not-implemented error on execute."""
    tool = all_tools.get("delegate")
    assert tool is not None, "delegate tool not found"

    result = asyncio.run(
        tool.execute({"agent": "test:agent", "instruction": "do something"})
    )

    assert result.success is False, "Expected DelegateTool stub to return success=False"
    assert result.error is not None, "Expected DelegateTool stub to return an error"

    # Verify the error message mentions stub / not implemented
    error_msg = (
        result.error.get("message", "")
        if isinstance(result.error, dict)
        else str(result.error)
    )
    assert "not yet implemented" in error_msg, (
        f"Expected 'not yet implemented' in error message, got: {error_msg!r}"
    )
