"""Tests for stub tools: mcp, recipes, apply_patch, python_check, shadow.

Verifies that all 5 stub tools are discoverable via scan_package and have
non-empty descriptions. Execution stubs return 'not yet implemented' errors.
"""

from __future__ import annotations

import asyncio

import pytest

from amplifier_ipc.protocol.discovery import scan_package

STUB_TOOL_NAMES = ["mcp", "recipes", "apply_patch", "python_check", "shadow"]


@pytest.fixture(scope="module")
def all_tools() -> dict:
    """Discover all tools via scan_package and return as name->instance dict."""
    components = scan_package("amplifier_foundation")
    return {getattr(t, "name", None): t() for t in components.get("tool", [])}


def test_all_stub_tools_discovered(all_tools: dict) -> None:
    """All 5 stub tools must be found by scan_package under the 'tool' component type."""
    missing = [name for name in STUB_TOOL_NAMES if name not in all_tools]
    assert not missing, (
        f"Stub tools not found by scan_package('amplifier_foundation'): {missing}. "
        f"Ensure stub tool files exist and are decorated with @tool."
    )


def test_all_stub_tools_have_description(all_tools: dict) -> None:
    """All stub tools must have a non-empty description longer than 10 characters."""
    for name in STUB_TOOL_NAMES:
        tool = all_tools.get(name)
        if tool is None:
            pytest.skip(f"Tool '{name}' not discovered — skipping description check")
        assert hasattr(tool, "description"), (
            f"Tool '{name}' missing 'description' attribute"
        )
        desc = tool.description
        assert isinstance(desc, str), f"Tool '{name}' description must be a string"
        assert len(desc.strip()) > 10, (
            f"Tool '{name}' description too short (must be >10 chars): {desc!r}"
        )


def test_all_stub_tools_have_input_schema(all_tools: dict) -> None:
    """All stub tools must have a non-empty input_schema dict."""
    for name in STUB_TOOL_NAMES:
        tool = all_tools.get(name)
        if tool is None:
            pytest.skip(f"Tool '{name}' not discovered — skipping schema check")
        assert hasattr(tool, "input_schema"), (
            f"Tool '{name}' missing 'input_schema' attribute"
        )
        schema = tool.input_schema
        assert isinstance(schema, dict), f"Tool '{name}' input_schema must be a dict"


def test_stub_tools_return_not_implemented(all_tools: dict) -> None:
    """All stub tools must return success=False with 'not yet implemented' error."""
    inputs = {
        "mcp": {},
        "recipes": {"operation": "list"},
        "apply_patch": {"type": "create_file", "path": "test.py"},
        "python_check": {},
        "shadow": {"operation": "list"},
    }
    for name in STUB_TOOL_NAMES:
        tool = all_tools.get(name)
        if tool is None:
            pytest.skip(f"Tool '{name}' not discovered — skipping execution check")
        result = asyncio.run(tool.execute(inputs.get(name, {})))
        assert result.success is False, (
            f"Stub tool '{name}' expected success=False but got True"
        )
        assert result.error is not None, f"Stub tool '{name}' expected error to be set"
        error_msg = (
            result.error.get("message", "")
            if isinstance(result.error, dict)
            else str(result.error)
        )
        assert "not yet implemented" in error_msg, (
            f"Stub tool '{name}' error should mention 'not yet implemented', got: {error_msg!r}"
        )
