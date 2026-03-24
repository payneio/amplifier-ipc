"""Tests for subdirectory tools (bash, filesystem, search) — verifies discovery and core behaviors."""

from __future__ import annotations

import asyncio
import pytest

from amplifier_ipc.protocol.discovery import scan_package


@pytest.fixture(scope="module")
def all_tools() -> dict:
    """Discover all tools via scan_package and return as name->instance dict."""
    components = scan_package("amplifier_foundation")
    return {getattr(t, "name", None): t() for t in components.get("tool", [])}


def test_bash_tool_discovered(all_tools: dict) -> None:
    """BashTool must be found by scan_package under the 'tool' component type."""
    assert "bash" in all_tools, (
        "BashTool with name='bash' not found by scan_package('amplifier_foundation'). "
        "Ensure tools/bash_tool.py exists and is decorated with @tool."
    )


def test_read_file_tool_discovered(all_tools: dict) -> None:
    """ReadTool must be found by scan_package under the 'tool' component type."""
    assert "read_file" in all_tools, (
        "ReadTool with name='read_file' not found by scan_package('amplifier_foundation'). "
        "Ensure tools/filesystem_tools.py exists and is decorated with @tool."
    )


def test_write_file_tool_discovered(all_tools: dict) -> None:
    """WriteTool must be found by scan_package under the 'tool' component type."""
    assert "write_file" in all_tools, (
        "WriteTool with name='write_file' not found by scan_package('amplifier_foundation'). "
        "Ensure tools/filesystem_tools.py exists and is decorated with @tool."
    )


def test_edit_file_tool_discovered(all_tools: dict) -> None:
    """EditTool must be found by scan_package under the 'tool' component type."""
    assert "edit_file" in all_tools, (
        "EditTool with name='edit_file' not found by scan_package('amplifier_foundation'). "
        "Ensure tools/filesystem_tools.py exists and is decorated with @tool."
    )


def test_grep_tool_discovered(all_tools: dict) -> None:
    """GrepTool must be found by scan_package under the 'tool' component type."""
    assert "grep" in all_tools, (
        "GrepTool with name='grep' not found by scan_package('amplifier_foundation'). "
        "Ensure tools/search_tools.py exists and is decorated with @tool."
    )


def test_glob_tool_discovered(all_tools: dict) -> None:
    """GlobTool must be found by scan_package under the 'tool' component type."""
    assert "glob" in all_tools, (
        "GlobTool with name='glob' not found by scan_package('amplifier_foundation'). "
        "Ensure tools/search_tools.py exists and is decorated with @tool."
    )


def test_bash_tool_rejects_empty_command(all_tools: dict) -> None:
    """BashTool must return failure when command is empty or missing."""
    tool = all_tools.get("bash")
    assert tool is not None, "bash tool not found"

    result = asyncio.run(tool.execute({}))

    assert result.success is False, "Expected failure when command is missing"
    assert result.error is not None, "Expected error to be set when command is missing"
