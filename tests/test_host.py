"""Tests for the Host orchestration class."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from amplifier_ipc_host.config import HostSettings, SessionConfig
from amplifier_ipc_host.events import (
    CompleteEvent,
    StreamContentBlockEndEvent,
    StreamContentBlockStartEvent,
    StreamTokenEvent,
)
from amplifier_ipc_host.host import Host
from amplifier_ipc_host.registry import CapabilityRegistry
from amplifier_ipc_host.router import Router


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClient:
    """Records calls and returns canned or callable responses."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._responses: dict[str, Any] = responses or {}

    async def request(self, method: str, params: Any = None) -> Any:
        self.calls.append((method, params))
        response = self._responses.get(method, {})
        if callable(response):
            return response(params)
        return response


class FakeService:
    """A minimal service stub with a FakeClient."""

    def __init__(self, client: FakeClient) -> None:
        self.client = client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_host_build_registry() -> None:
    """_build_registry sends describe to each service and populates the registry.

    The real IPC protocol server returns a nested format with a 'capabilities'
    wrapper and 'content' as {'paths': [...]} rather than a flat list.
    _build_registry must extract and flatten this before calling registry.register().
    """
    # This is the REAL format returned by the protocol Server.describe() handler:
    describe_result = {
        "name": "foundation",
        "capabilities": {
            "tools": [{"name": "bash", "description": "Run bash commands"}],
            "hooks": [],
            "orchestrators": [{"name": "loop"}],
            "context_managers": [{"name": "simple"}],
            "providers": [{"name": "anthropic"}],
            "content": {"paths": ["agents/readme.md", "context/base.md"]},
        },
    }

    client = FakeClient(responses={"describe": describe_result})
    service = FakeService(client)

    config = SessionConfig(
        services=["foundation"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()

    host = Host(config=config, settings=settings)
    # Inject fake services directly (bypass spawn)
    host._services = {"foundation": service}

    await host._build_registry()

    # Verify describe was called on the service
    assert len(client.calls) == 1
    assert client.calls[0][0] == "describe"

    # Verify registry was populated correctly
    assert host._registry.get_tool_service("bash") == "foundation"
    assert host._registry.get_orchestrator_service("loop") == "foundation"
    assert host._registry.get_context_manager_service("simple") == "foundation"
    assert host._registry.get_provider_service("anthropic") == "foundation"


async def test_host_route_orchestrator_message() -> None:
    """_handle_orchestrator_request delegates to Router.route_request."""
    registry = CapabilityRegistry()
    registry.register(
        "foundation",
        {
            "tools": [{"name": "bash", "description": "Run bash"}],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": [],
        },
    )

    tool_client = FakeClient(responses={"tool.execute": {"output": "hello world"}})
    ctx_client = FakeClient()
    provider_client = FakeClient()

    services: dict[str, Any] = {
        "foundation": FakeService(tool_client),
        "ctx": FakeService(ctx_client),
        "provider": FakeService(provider_client),
    }

    config = SessionConfig(
        services=["foundation"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()

    host = Host(config=config, settings=settings)
    host._registry = registry
    host._services = services
    host._router = Router(
        registry=registry,
        services=services,
        context_manager_key="ctx",
        provider_key="provider",
    )

    result = await host._handle_orchestrator_request(
        "request.tool_execute",
        {"tool_name": "bash", "arguments": {"command": "echo hello"}},
    )

    assert result == {"output": "hello world"}
    assert len(tool_client.calls) == 1
    assert tool_client.calls[0][0] == "tool.execute"
    assert tool_client.calls[0][1]["tool_name"] == "bash"


async def test_orchestrator_loop_raises_on_error_response() -> None:
    """_orchestrator_loop raises RuntimeError when orchestrator returns a JSON-RPC error."""
    config = SessionConfig(
        services=["orch"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()

    host = Host(config=config, settings=settings)

    # Fake process with non-None stdin/stdout so the pipe check passes
    fake_process = MagicMock()
    fake_process.stdin = MagicMock()
    fake_process.stdout = MagicMock()

    fake_service = MagicMock()
    fake_service.process = fake_process
    host._services = {"orch": fake_service}

    # Capture the execute_id written by the loop so we can echo it back
    captured_id: list[str] = []

    async def fake_write(stream: object, message: dict) -> None:  # type: ignore[type-arg]
        if message.get("method") == "orchestrator.execute":
            captured_id.append(message["id"])

    read_call_count = 0

    async def fake_read(stream: object) -> dict | None:  # type: ignore[type-arg]
        nonlocal read_call_count
        read_call_count += 1
        if read_call_count == 1:
            # Return an error response matching the execute_id
            return {
                "jsonrpc": "2.0",
                "id": captured_id[0],
                "error": {"code": -32603, "message": "Internal orchestrator error"},
            }
        # If the loop doesn't handle the error and iterates, return None to break it
        return None

    with (
        patch("amplifier_ipc_host.host.write_message", fake_write),
        patch("amplifier_ipc_host.host.read_message", fake_read),
    ):
        with pytest.raises(RuntimeError, match="Orchestrator returned error"):
            async for _ in host._orchestrator_loop(
                orchestrator_key="orch",
                prompt="hello",
                system_prompt="be helpful",
            ):
                pass


async def test_orchestrator_loop_yields_stream_events() -> None:
    """_orchestrator_loop yields StreamTokenEvent events then a CompleteEvent."""
    config = SessionConfig(
        services=["orch"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
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

    read_call_count = 0

    async def fake_read(stream: object) -> dict | None:  # type: ignore[type-arg]
        nonlocal read_call_count
        read_call_count += 1
        if read_call_count == 1:
            return {
                "jsonrpc": "2.0",
                "method": "stream.token",
                "params": {"token": "Hello"},
            }
        elif read_call_count == 2:
            return {
                "jsonrpc": "2.0",
                "method": "stream.token",
                "params": {"token": " World"},
            }
        else:
            # Final response matching execute_id
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

    assert len(events) == 3
    assert isinstance(events[0], StreamTokenEvent)
    assert events[0].token == "Hello"
    assert isinstance(events[1], StreamTokenEvent)
    assert events[1].token == " World"
    assert isinstance(events[2], CompleteEvent)
    assert events[2].result == "Hello World"


async def test_orchestrator_loop_yields_content_block_events() -> None:
    """_orchestrator_loop yields StreamContentBlockStartEvent, StreamTokenEvent,
    StreamContentBlockEndEvent, then CompleteEvent for a full content-block sequence."""
    config = SessionConfig(
        services=["orch"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
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

    read_call_count = 0

    async def fake_read(stream: object) -> dict | None:  # type: ignore[type-arg]
        nonlocal read_call_count
        read_call_count += 1
        if read_call_count == 1:
            return {
                "jsonrpc": "2.0",
                "method": "stream.content_block_start",
                "params": {"block_type": "text", "index": 0},
            }
        elif read_call_count == 2:
            return {
                "jsonrpc": "2.0",
                "method": "stream.token",
                "params": {"token": "Hello"},
            }
        elif read_call_count == 3:
            return {
                "jsonrpc": "2.0",
                "method": "stream.content_block_end",
                "params": {},
            }
        else:
            # Final response
            return {
                "jsonrpc": "2.0",
                "id": captured_id[0],
                "result": "Hello",
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

    assert len(events) == 4
    assert isinstance(events[0], StreamContentBlockStartEvent)
    assert events[0].block_type == "text"
    assert events[0].index == 0
    assert isinstance(events[1], StreamTokenEvent)
    assert events[1].token == "Hello"
    assert isinstance(events[2], StreamContentBlockEndEvent)
    assert events[2].block_type == ""
    assert events[2].index == 0
    assert isinstance(events[3], CompleteEvent)
    assert events[3].result == "Hello"
