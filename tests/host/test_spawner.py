"""Tests for spawner.py - sub-session spawning utilities."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from amplifier_ipc.host.spawner import (
    SpawnRequest,
    _run_child_session,
    check_self_delegation_depth,
    filter_hooks,
    filter_tools,
    format_parent_context,
    generate_child_session_id,
    merge_configs,
    spawn_child_session,
)


# ---------------------------------------------------------------------------
# SpawnRequest is a Pydantic BaseModel (1 test)
# ---------------------------------------------------------------------------


def test_spawn_request_is_pydantic_base_model() -> None:
    """SpawnRequest must be a Pydantic BaseModel (not a dataclass)."""
    assert issubclass(SpawnRequest, BaseModel), (
        "SpawnRequest must inherit from pydantic.BaseModel"
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
    """Raises ValueError when current_depth equals max_depth."""
    with pytest.raises(ValueError):
        check_self_delegation_depth(current_depth=3, max_depth=3)


def test_check_self_delegation_depth_raises_beyond_limit() -> None:
    """Raises ValueError when current_depth exceeds max_depth."""
    with pytest.raises(ValueError):
        check_self_delegation_depth(current_depth=5, max_depth=3)


def test_check_self_delegation_depth_allows_below_limit() -> None:
    """Does not raise when current_depth is below max_depth."""
    check_self_delegation_depth(current_depth=2, max_depth=3)  # must not raise


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


# ---------------------------------------------------------------------------
# format_parent_context — additional focused tests (3)
# ---------------------------------------------------------------------------


def test_format_parent_context_none_returns_empty() -> None:
    """depth='none' always returns empty string regardless of transcript content."""
    transcript = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]
    result = format_parent_context(transcript, "none", "conversation", 10)
    assert result == ""


def test_format_parent_context_recent_limits_turns() -> None:
    """depth='recent' returns only the last context_turns messages after scope filter."""
    transcript = [
        {"role": "user", "content": "msg1"},
        {"role": "assistant", "content": "msg2"},
        {"role": "user", "content": "msg3"},
        {"role": "assistant", "content": "msg4"},
        {"role": "user", "content": "msg5"},
    ]
    result = format_parent_context(transcript, "recent", "conversation", 2)
    assert "msg5" in result
    assert "msg4" in result
    assert "msg3" not in result
    assert "msg1" not in result


def test_format_parent_context_all_includes_everything() -> None:
    """depth='all' includes all messages that pass the scope filter."""
    transcript = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "tool_result", "content": "third"},
    ]
    # scope=conversation filters out tool_result; depth=all keeps all that remain
    result = format_parent_context(transcript, "all", "conversation", 0)
    assert "first" in result
    assert "second" in result
    assert "third" not in result


# ---------------------------------------------------------------------------
# _run_child_session (2 tests)
# ---------------------------------------------------------------------------


async def test_run_child_session_creates_host_and_runs() -> None:
    """Host is created with SessionConfig/HostSettings; CompleteEvent result is returned."""
    from amplifier_ipc.host.events import CompleteEvent

    async def mock_run(prompt: str):  # type: ignore[return]
        yield CompleteEvent(result="Hello from child")

    with patch("amplifier_ipc.host.host.Host") as MockHost:
        mock_host_instance = MagicMock()
        MockHost.return_value = mock_host_instance
        mock_host_instance.run = mock_run

        result = await _run_child_session(
            child_session_id="child-123",
            child_config={
                "services": ["svc"],
                "orchestrator": "orch",
                "context_manager": "cm",
                "provider": "prov",
            },
            instruction="Hello child",
            request=SpawnRequest(agent="self", instruction="Hello child"),
        )

    assert MockHost.called
    assert result["session_id"] == "child-123"
    assert result["response"] == "Hello from child"
    assert "turn_count" in result
    assert "metadata" in result


async def test_run_child_session_handles_no_complete_event() -> None:
    """Returns empty response when no CompleteEvent is yielded by the host."""
    from amplifier_ipc.host.events import StreamTokenEvent

    async def mock_run_no_complete(prompt: str):  # type: ignore[return]
        yield StreamTokenEvent(token="some token")

    with patch("amplifier_ipc.host.host.Host") as MockHost:
        mock_host_instance = MagicMock()
        MockHost.return_value = mock_host_instance
        mock_host_instance.run = mock_run_no_complete

        result = await _run_child_session(
            child_session_id="child-456",
            child_config={},
            instruction="Do something",
            request=SpawnRequest(agent="self", instruction="Do something"),
        )

    assert result["session_id"] == "child-456"
    assert result["response"] == ""


# ---------------------------------------------------------------------------
# spawn_child_session (3 tests - async)
# ---------------------------------------------------------------------------


async def test_spawn_child_session_depth_limit_exceeded() -> None:
    """Raises ValueError when current_depth >= 3 (default max_depth)."""
    request = SpawnRequest(agent="self", instruction="Do something")
    with pytest.raises(ValueError):
        await spawn_child_session(
            parent_session_id="parent-123",
            parent_config={"tools": []},
            transcript=[],
            request=request,
            current_depth=3,
        )


async def test_spawn_child_session_self_delegation() -> None:
    """Self-delegation clones parent config, excludes delegate tool, calls _run_child_session."""
    parent_config = {
        "tools": [
            {"name": "bash"},
            {"name": "delegate"},
            {"name": "grep"},
        ],
        "hooks": [{"name": "pre-request"}],
    }
    request = SpawnRequest(agent="self", instruction="Do something")

    with patch(
        "amplifier_ipc.host.spawner._run_child_session", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = {
            "session_id": "child-123",
            "response": "result",
            "turn_count": 1,
            "metadata": {},
        }
        await spawn_child_session(
            parent_session_id="parent-123",
            parent_config=parent_config,
            transcript=[],
            request=request,
            current_depth=0,
        )

    assert mock_run.called
    # Extract child_config — second positional argument to _run_child_session
    positional_args = mock_run.call_args[0]
    child_config = positional_args[1]
    tool_names = [t["name"] for t in child_config.get("tools", [])]
    assert "delegate" not in tool_names
    assert "bash" in tool_names
    assert "grep" in tool_names


async def test_spawn_child_session_recent_depth_requires_context_turns() -> None:
    """Raises ValueError when context_depth='recent' but context_turns is not set."""
    request = SpawnRequest(
        agent="self",
        instruction="Do something",
        context_depth="recent",
        context_turns=None,  # not set — should be caught
    )
    with pytest.raises(ValueError, match="context_turns"):
        await spawn_child_session(
            parent_session_id="parent-123",
            parent_config={"tools": []},
            transcript=[{"role": "user", "content": "hi"}],
            request=request,
            current_depth=0,
        )


# ---------------------------------------------------------------------------
# shared_services / shared_registry forwarding (3 tests)
# ---------------------------------------------------------------------------


async def test_run_child_session_passes_shared_services_to_host() -> None:
    """_run_child_session forwards shared_services and shared_registry to Host."""
    from amplifier_ipc.host.events import CompleteEvent
    from amplifier_ipc.host.service_index import ServiceIndex

    async def mock_run(prompt: str):  # type: ignore[return]
        yield CompleteEvent(result="done")

    shared_svcs = {"svc": object()}
    shared_reg = ServiceIndex()

    with patch("amplifier_ipc.host.host.Host") as MockHost:
        mock_instance = MagicMock()
        MockHost.return_value = mock_instance
        mock_instance.run = mock_run

        await _run_child_session(
            child_session_id="child-789",
            child_config={
                "services": ["svc"],
                "orchestrator": "o",
                "context_manager": "cm",
                "provider": "p",
            },
            instruction="go",
            request=SpawnRequest(agent="self", instruction="go"),
            shared_services=shared_svcs,
            shared_registry=shared_reg,
        )

    # Verify Host was constructed with shared_services and shared_registry
    _, kwargs = MockHost.call_args
    assert kwargs.get("shared_services") is shared_svcs
    assert kwargs.get("shared_registry") is shared_reg


async def test_spawn_child_session_forwards_shared_services() -> None:
    """spawn_child_session passes shared_services and shared_registry to _run_child_session."""
    shared_svcs = {"svc": object()}
    shared_reg = object()
    request = SpawnRequest(agent="self", instruction="Do something")

    with patch(
        "amplifier_ipc.host.spawner._run_child_session", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = {
            "session_id": "child-123",
            "response": "result",
            "turn_count": 1,
            "metadata": {},
        }
        await spawn_child_session(
            parent_session_id="parent-123",
            parent_config={"tools": []},
            transcript=[],
            request=request,
            current_depth=0,
            shared_services=shared_svcs,
            shared_registry=shared_reg,
        )

    assert mock_run.called
    _, kwargs = mock_run.call_args
    assert kwargs.get("shared_services") is shared_svcs
    assert kwargs.get("shared_registry") is shared_reg


async def test_run_child_session_without_shared_services_passes_none() -> None:
    """When no shared_services given, Host receives None (will spawn its own)."""
    from amplifier_ipc.host.events import CompleteEvent

    async def mock_run(prompt: str):  # type: ignore[return]
        yield CompleteEvent(result="done")

    with patch("amplifier_ipc.host.host.Host") as MockHost:
        mock_instance = MagicMock()
        MockHost.return_value = mock_instance
        mock_instance.run = mock_run

        await _run_child_session(
            child_session_id="child-no-shared",
            child_config={},
            instruction="go",
            request=SpawnRequest(agent="self", instruction="go"),
            # No shared_services or shared_registry
        )

    _, kwargs = MockHost.call_args
    assert kwargs.get("shared_services") is None
    assert kwargs.get("shared_registry") is None


# ---------------------------------------------------------------------------
# event_callback forwarding (3 tests)
# ---------------------------------------------------------------------------


async def test_run_child_session_calls_event_callback() -> None:
    """event_callback receives all events yielded by Host.run()."""
    from amplifier_ipc.host.events import CompleteEvent, StreamTokenEvent

    async def mock_run(prompt: str):  # type: ignore[return]
        yield StreamTokenEvent(token="token1")
        yield StreamTokenEvent(token="token2")
        yield CompleteEvent(result="done")

    received_events: list = []

    with patch("amplifier_ipc.host.host.Host") as MockHost:
        mock_host_instance = MagicMock()
        MockHost.return_value = mock_host_instance
        mock_host_instance.run = mock_run

        await _run_child_session(
            child_session_id="child-callback-test",
            child_config={},
            instruction="Do something",
            request=SpawnRequest(agent="self", instruction="Do something"),
            event_callback=received_events.append,
        )

    assert len(received_events) == 3
    assert isinstance(received_events[0], StreamTokenEvent)
    assert isinstance(received_events[1], StreamTokenEvent)
    assert isinstance(received_events[2], CompleteEvent)


async def test_run_child_session_no_callback_still_works() -> None:
    """_run_child_session works correctly without event_callback (backward compat)."""
    from amplifier_ipc.host.events import CompleteEvent

    async def mock_run(prompt: str):  # type: ignore[return]
        yield CompleteEvent(result="backward compat result")

    with patch("amplifier_ipc.host.host.Host") as MockHost:
        mock_host_instance = MagicMock()
        MockHost.return_value = mock_host_instance
        mock_host_instance.run = mock_run

        result = await _run_child_session(
            child_session_id="child-no-callback",
            child_config={},
            instruction="Do something",
            request=SpawnRequest(agent="self", instruction="Do something"),
            # No event_callback - should default to None
        )

    assert result["response"] == "backward compat result"
    assert result["turn_count"] == 1


async def test_spawn_child_session_forwards_event_callback() -> None:
    """spawn_child_session passes event_callback through to _run_child_session."""
    request = SpawnRequest(agent="self", instruction="Do something")
    callback = MagicMock()

    with patch(
        "amplifier_ipc.host.spawner._run_child_session", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = {
            "session_id": "child-123",
            "response": "result",
            "turn_count": 1,
            "metadata": {},
        }
        await spawn_child_session(
            parent_session_id="parent-123",
            parent_config={"tools": []},
            transcript=[],
            request=request,
            current_depth=0,
            event_callback=callback,
        )

    assert mock_run.called
    _, kwargs = mock_run.call_args
    assert kwargs.get("event_callback") is callback
