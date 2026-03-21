"""Tests for spawner.py - sub-session spawning utilities."""

from __future__ import annotations

import re

import pytest

from amplifier_ipc_host.spawner import (
    check_self_delegation_depth,
    filter_hooks,
    filter_tools,
    format_parent_context,
    generate_child_session_id,
    merge_configs,
)


# ---------------------------------------------------------------------------
# generate_child_session_id (2 tests)
# ---------------------------------------------------------------------------


def test_generate_child_session_id_format() -> None:
    """Session ID follows {parent}-{child_span}_{agent} format."""
    parent_session_id = "abc123"
    agent_name = "my-agent"

    result = generate_child_session_id(parent_session_id, agent_name)

    pattern = re.compile(r"^abc123-[0-9a-f]{8}_my-agent$")
    assert pattern.match(result), (
        f"Expected format abc123-<8hex>_my-agent, got: {result}"
    )


def test_generate_child_session_id_unique() -> None:
    """Each call produces a distinct child session ID."""
    result1 = generate_child_session_id("parent", "agent")
    result2 = generate_child_session_id("parent", "agent")

    assert result1 != result2


# ---------------------------------------------------------------------------
# merge_configs (2 tests)
# ---------------------------------------------------------------------------


def test_merge_configs_scalar_override() -> None:
    """Child scalar values override parent; missing child keys fall back to parent."""
    parent = {"model": "gpt-3.5", "temperature": 0.5, "max_tokens": 100}
    child = {"model": "gpt-4", "temperature": 0.7}

    result = merge_configs(parent, child)

    assert result["model"] == "gpt-4"  # child overrides
    assert result["temperature"] == 0.7  # child overrides
    assert result["max_tokens"] == 100  # parent preserved


def test_merge_configs_list_by_name() -> None:
    """Tool lists merge by name; child entry wins on name collision."""
    parent = {
        "tools": [
            {"name": "bash", "timeout": 30},
            {"name": "grep", "timeout": 10},
        ]
    }
    child = {
        "tools": [
            {"name": "bash", "timeout": 60},  # override parent bash
            {"name": "python", "timeout": 15},  # new tool from child
        ]
    }

    result = merge_configs(parent, child)

    tools_by_name = {t["name"]: t for t in result["tools"]}

    assert tools_by_name["bash"]["timeout"] == 60  # child override
    assert tools_by_name["grep"]["timeout"] == 10  # parent preserved
    assert tools_by_name["python"]["timeout"] == 15  # child added


# ---------------------------------------------------------------------------
# filter_tools (3 tests)
# ---------------------------------------------------------------------------


def test_filter_tools_default_excludes_delegate() -> None:
    """Default behaviour excludes 'delegate' to prevent infinite recursion."""
    tools = [
        {"name": "bash"},
        {"name": "delegate"},
        {"name": "grep"},
    ]

    result = filter_tools(tools, exclude_tools=None, inherit_tools=None)

    names = [t["name"] for t in result]
    assert "delegate" not in names
    assert "bash" in names
    assert "grep" in names


def test_filter_tools_blocklist() -> None:
    """exclude_tools removes named tools (blocklist mode)."""
    tools = [
        {"name": "bash"},
        {"name": "grep"},
        {"name": "python"},
    ]

    result = filter_tools(tools, exclude_tools=["bash", "python"], inherit_tools=None)

    names = [t["name"] for t in result]
    assert "bash" not in names
    assert "python" not in names
    assert "grep" in names


def test_filter_tools_allowlist() -> None:
    """inherit_tools keeps only named tools (allowlist mode)."""
    tools = [
        {"name": "bash"},
        {"name": "grep"},
        {"name": "python"},
        {"name": "delegate"},
    ]

    result = filter_tools(tools, exclude_tools=None, inherit_tools=["bash", "grep"])

    names = [t["name"] for t in result]
    assert "bash" in names
    assert "grep" in names
    assert "python" not in names
    assert "delegate" not in names


# ---------------------------------------------------------------------------
# filter_hooks (1 test)
# ---------------------------------------------------------------------------


def test_filter_hooks_no_default_excludes() -> None:
    """filter_hooks with no options returns all hooks (no default excludes)."""
    hooks = [
        {"name": "pre-request"},
        {"name": "post-response"},
        {"name": "on-error"},
    ]

    result = filter_hooks(hooks, exclude_hooks=None, inherit_hooks=None)

    names = [h["name"] for h in result]
    assert "pre-request" in names
    assert "post-response" in names
    assert "on-error" in names


# ---------------------------------------------------------------------------
# check_self_delegation_depth (1 test)
# ---------------------------------------------------------------------------


def test_check_self_delegation_depth_raises_at_limit() -> None:
    """Raises ValueError when current_depth >= max_depth; allows below limit."""
    # At limit — must raise
    with pytest.raises(ValueError):
        check_self_delegation_depth(current_depth=3, max_depth=3)

    # Beyond limit — must raise
    with pytest.raises(ValueError):
        check_self_delegation_depth(current_depth=5, max_depth=3)

    # Below limit — must not raise
    check_self_delegation_depth(current_depth=2, max_depth=3)


# ---------------------------------------------------------------------------
# format_parent_context (1 test)
# ---------------------------------------------------------------------------


def test_format_parent_context_depth_and_scope() -> None:
    """Exercises depth=none/recent/all and scope=conversation filtering."""
    transcript = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "tool_result", "content": "some output"},
        {"role": "user", "content": "What now?"},
        {"role": "assistant", "content": "Let me help"},
    ]

    # depth=none → empty regardless of scope
    assert format_parent_context(transcript, "none", "conversation", 5) == ""

    # depth=all + scope=conversation → only user/assistant messages
    result_all = format_parent_context(transcript, "all", "conversation", 5)
    assert "tool_result" not in result_all
    assert "Hello" in result_all
    assert "Hi there" in result_all

    # depth=recent + context_turns=2 + scope=conversation → last 2 user/assistant messages
    result_recent = format_parent_context(transcript, "recent", "conversation", 2)
    # Last 2 conversation messages
    assert "What now?" in result_recent
    assert "Let me help" in result_recent
    # Earlier messages should not appear
    assert "Hello" not in result_recent
