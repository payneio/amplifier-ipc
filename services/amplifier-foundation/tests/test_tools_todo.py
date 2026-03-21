"""Tests for TodoTool — verifies discovery, attributes, and core operations."""

from __future__ import annotations

import asyncio
import pytest

from amplifier_ipc_protocol.discovery import scan_package


@pytest.fixture(scope="module")
def todo_tool():
    """Discover and return the TodoTool instance via scan_package."""
    components = scan_package("amplifier_foundation")
    tools = components.get("tool", [])
    for t in tools:
        if getattr(t, "name", None) == "todo":
            return t
    return None


def test_todo_tool_discovered(todo_tool) -> None:
    """TodoTool must be found by scan_package under the 'tool' component type."""
    assert todo_tool is not None, (
        "TodoTool with name='todo' not found by scan_package('amplifier_foundation'). "
        "Ensure tools/todo.py exists and is decorated with @tool."
    )


def test_todo_tool_has_required_attributes(todo_tool) -> None:
    """TodoTool must have name, description, and input_schema attributes."""
    assert todo_tool is not None
    assert hasattr(todo_tool, "name"), "TodoTool missing 'name' attribute"
    assert todo_tool.name == "todo"

    assert hasattr(todo_tool, "description"), "TodoTool missing 'description' attribute"
    assert isinstance(todo_tool.description, str)
    assert len(todo_tool.description.strip()) > 0

    assert hasattr(todo_tool, "input_schema"), (
        "TodoTool missing 'input_schema' attribute"
    )
    assert isinstance(todo_tool.input_schema, dict)
    # input_schema must have action enum with create/update/list
    props = todo_tool.input_schema.get("properties", {})
    assert "action" in props, "input_schema missing 'action' property"
    assert "todos" in props, "input_schema missing 'todos' property"
    action_enum = props["action"].get("enum", [])
    assert "create" in action_enum
    assert "update" in action_enum
    assert "list" in action_enum


def test_todo_tool_create(todo_tool) -> None:
    """Create action stores todos and returns count in output."""
    assert todo_tool is not None

    todos = [
        {
            "content": "Write tests",
            "status": "in_progress",
            "activeForm": "Writing tests",
        },
        {
            "content": "Implement code",
            "status": "pending",
            "activeForm": "Implementing code",
        },
    ]
    result = asyncio.run(todo_tool.execute({"action": "create", "todos": todos}))

    assert result.success is True
    assert result.output is not None
    assert result.output["count"] == 2
    assert result.output["todos"] == todos


def test_todo_tool_list(todo_tool) -> None:
    """List action returns the todos that were previously created."""
    assert todo_tool is not None

    # First create some todos
    todos = [
        {"content": "Task A", "status": "pending", "activeForm": "Doing task A"},
    ]
    asyncio.run(todo_tool.execute({"action": "create", "todos": todos}))

    # Now list them
    result = asyncio.run(todo_tool.execute({"action": "list"}))
    assert result.success is True
    assert result.output is not None
    assert result.output["count"] == 1
    assert result.output["todos"] == todos
