"""Integration tests for all three protocol extensions.

Tests state, streaming, and spawning through the Router and Host
infrastructure using fake services.  Each test exercises a complete
end-to-end flow through the components that were implemented in Tasks
4–11 of Phase 1.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from amplifier_ipc_host.config import HostSettings, SessionConfig
from amplifier_ipc_host.events import (
    CompleteEvent,
    StreamContentBlockEndEvent,
    StreamContentBlockStartEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
)
from amplifier_ipc_host.host import Host
from amplifier_ipc_host.registry import CapabilityRegistry
from amplifier_ipc_host.router import Router


# ---------------------------------------------------------------------------
# Fakes (same pattern as test_router.py)
# ---------------------------------------------------------------------------


class FakeClient:
    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._responses: dict[str, Any] = responses or {}
        self.on_notification = None

    async def request(self, method: str, params: Any = None) -> Any:
        self.calls.append((method, params))
        if method in self._responses:
            return self._responses[method]
        return {}


class FakeService:
    def __init__(self, client: FakeClient) -> None:
        self.client = client


# ---------------------------------------------------------------------------
# Test 1: State round-trip through router
# ---------------------------------------------------------------------------


async def test_state_set_then_get_round_trip() -> None:
    """state.set followed by state.get returns the value through the router."""
    registry = CapabilityRegistry()
    registry.register(
        "foundation",
        {
            "tools": [{"name": "bash", "description": "Run bash"}],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [{"name": "simple"}],
            "providers": [],
            "content": [],
        },
    )
    registry.register(
        "providers",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [{"name": "mock"}],
            "content": [],
        },
    )

    services: dict[str, Any] = {
        "foundation": FakeService(FakeClient()),
        "providers": FakeService(FakeClient()),
    }

    router = Router(
        registry=registry,
        services=services,
        context_manager_key="foundation",
        provider_key="providers",
    )

    # Set a value
    set_result = await router.route_request(
        "request.state_set",
        {"key": "todo_state", "value": {"items": ["buy milk", "write tests"]}},
    )
    assert set_result == {"ok": True}

    # Get the value back
    get_result = await router.route_request(
        "request.state_get",
        {"key": "todo_state"},
    )
    assert get_result == {"value": {"items": ["buy milk", "write tests"]}}

    # Get a missing key returns None
    missing_result = await router.route_request(
        "request.state_get",
        {"key": "nonexistent"},
    )
    assert missing_result == {"value": None}


# ---------------------------------------------------------------------------
# Test 2: Full streaming event sequence through orchestrator loop
# ---------------------------------------------------------------------------


async def test_full_streaming_event_sequence() -> None:
    """Orchestrator loop yields complete streaming sequence:
    content_block_start → thinking → tokens → content_block_end → complete."""
    config = SessionConfig(
        services=["orch"],
        orchestrator="loop",
        context_manager="simple",
        provider="mock",
    )
    settings = HostSettings()
    host = Host(config=config, settings=settings)

    fake_process = MagicMock()
    fake_process.stdin = MagicMock()
    fake_process.stdout = MagicMock()
    fake_service = MagicMock()
    fake_service.process = fake_process
    host._services = {"orch": fake_service}

    captured_id: list[str] = []

    async def fake_write(stream: object, message: dict) -> None:  # type: ignore[type-arg]
        if message.get("method") == "orchestrator.execute":
            captured_id.append(message["id"])

    # Sequence mirrors a real Anthropic streaming turn with a thinking block
    # followed by a text block.  Note: host reads block_type from params, not type.
    messages = [
        {
            "jsonrpc": "2.0",
            "method": "stream.content_block_start",
            "params": {"block_type": "thinking", "index": 0},
        },
        {
            "jsonrpc": "2.0",
            "method": "stream.thinking",
            "params": {"thinking": "Let me think..."},
        },
        {
            "jsonrpc": "2.0",
            "method": "stream.content_block_end",
            "params": {"block_type": "thinking", "index": 0},
        },
        {
            "jsonrpc": "2.0",
            "method": "stream.content_block_start",
            "params": {"block_type": "text", "index": 1},
        },
        {
            "jsonrpc": "2.0",
            "method": "stream.token",
            "params": {"token": "Hello"},
        },
        {
            "jsonrpc": "2.0",
            "method": "stream.token",
            "params": {"token": " World"},
        },
        {
            "jsonrpc": "2.0",
            "method": "stream.content_block_end",
            "params": {"block_type": "text", "index": 1},
        },
    ]
    read_idx = 0

    async def fake_read(stream: object) -> dict | None:  # type: ignore[type-arg]
        nonlocal read_idx
        idx = read_idx
        read_idx += 1
        if idx < len(messages):
            return messages[idx]
        # Final response
        return {
            "jsonrpc": "2.0",
            "id": captured_id[0],
            "result": "Hello World",
        }

    with (
        patch("amplifier_ipc_host.host.write_message", fake_write),
        patch("amplifier_ipc_host.host.read_message", fake_read),
    ):
        events = []
        async for event in host._orchestrator_loop(
            orchestrator_key="orch",
            prompt="hello",
            system_prompt="be helpful",
        ):
            events.append(event)

    assert len(events) == 8  # 7 stream events + 1 complete

    assert isinstance(events[0], StreamContentBlockStartEvent)
    assert events[0].block_type == "thinking"
    assert events[0].index == 0

    assert isinstance(events[1], StreamThinkingEvent)
    assert events[1].thinking == "Let me think..."

    assert isinstance(events[2], StreamContentBlockEndEvent)
    assert events[2].block_type == "thinking"

    assert isinstance(events[3], StreamContentBlockStartEvent)
    assert events[3].block_type == "text"
    assert events[3].index == 1

    assert isinstance(events[4], StreamTokenEvent)
    assert events[4].token == "Hello"

    assert isinstance(events[5], StreamTokenEvent)
    assert events[5].token == " World"

    assert isinstance(events[6], StreamContentBlockEndEvent)
    assert events[6].block_type == "text"

    assert isinstance(events[7], CompleteEvent)
    assert events[7].result == "Hello World"


# ---------------------------------------------------------------------------
# Test 3: Spawn handler is routable through the router
# ---------------------------------------------------------------------------


async def test_spawn_handler_receives_correct_params() -> None:
    """request.session_spawn passes all params to spawn handler unchanged."""
    registry = CapabilityRegistry()
    services: dict[str, Any] = {
        "ctx": FakeService(FakeClient()),
        "prov": FakeService(FakeClient()),
    }

    spawn_params_received: list[Any] = []

    async def mock_spawn(params: Any) -> Any:
        spawn_params_received.append(params)
        return {
            "session_id": "parent-child_test",
            "response": "Child completed",
            "turn_count": 1,
            "metadata": {"agent": params.get("agent")},
        }

    router = Router(
        registry=registry,
        services=services,
        context_manager_key="ctx",
        provider_key="prov",
        spawn_handler=mock_spawn,
    )

    result = await router.route_request(
        "request.session_spawn",
        {
            "agent": "explorer",
            "instruction": "Find all Python files",
            "context_depth": "recent",
            "context_turns": 5,
            "exclude_tools": ["web_search"],
        },
    )

    assert result["response"] == "Child completed"
    assert result["metadata"]["agent"] == "explorer"
    assert len(spawn_params_received) == 1
    received = spawn_params_received[0]
    assert received["agent"] == "explorer"
    assert received["context_depth"] == "recent"
    assert received["exclude_tools"] == ["web_search"]


# ---------------------------------------------------------------------------
# Test 4: State persists across set/get within a single router instance
# ---------------------------------------------------------------------------


async def test_state_persists_across_multiple_operations() -> None:
    """Multiple state.set calls accumulate; state.get reads the latest value."""
    registry = CapabilityRegistry()
    services: dict[str, Any] = {
        "ctx": FakeService(FakeClient()),
        "prov": FakeService(FakeClient()),
    }

    router = Router(
        registry=registry,
        services=services,
        context_manager_key="ctx",
        provider_key="prov",
    )

    # Set multiple keys
    await router.route_request("request.state_set", {"key": "counter", "value": 1})
    await router.route_request("request.state_set", {"key": "name", "value": "test"})
    # Overwrite counter
    await router.route_request("request.state_set", {"key": "counter", "value": 2})

    # Read them back
    counter = await router.route_request("request.state_get", {"key": "counter"})
    name = await router.route_request("request.state_get", {"key": "name"})

    assert counter == {"value": 2}
    assert name == {"value": "test"}
