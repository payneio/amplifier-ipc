"""Tests for the Host orchestration class."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from amplifier_ipc.host.config import HostSettings, SessionConfig
from amplifier_ipc.host.events import (
    ApprovalRequestEvent,
    CompleteEvent,
    StreamContentBlockEndEvent,
    StreamContentBlockStartEvent,
    StreamTokenEvent,
)
from amplifier_ipc.host.host import Host
from amplifier_ipc.host.registry import CapabilityRegistry
from amplifier_ipc.host.router import Router


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
        patch("amplifier_ipc.host.host.write_message", fake_write),
        patch("amplifier_ipc.host.host.read_message", fake_read),
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
        patch("amplifier_ipc.host.host.write_message", fake_write),
        patch("amplifier_ipc.host.host.read_message", fake_read),
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


async def test_host_routes_session_spawn_to_spawner() -> None:
    """_handle_orchestrator_request routes request.session_spawn to the spawn handler."""
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

    services: dict[str, Any] = {
        "foundation": FakeService(FakeClient()),
        "ctx": FakeService(FakeClient()),
        "provider": FakeService(FakeClient()),
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

    spawn_called_with: list[Any] = []

    async def mock_spawn(params: Any) -> Any:
        spawn_called_with.append(params)
        return {
            "session_id": "parent-child_explorer",
            "response": "Done",
            "turn_count": 1,
            "metadata": {},
        }

    host._router = Router(
        registry=registry,
        services=services,
        context_manager_key="ctx",
        provider_key="provider",
        spawn_handler=mock_spawn,
    )

    result = await host._handle_orchestrator_request(
        "request.session_spawn",
        {"agent": "explorer", "instruction": "Find files"},
    )

    assert result["response"] == "Done"
    assert len(spawn_called_with) == 1


async def test_host_spawn_handler_passes_parent_config() -> None:
    """_build_spawn_handler builds a closure that passes actual parent_config to spawn_child_session.

    Verifies that parent_config contains real data from _config and _registry,
    not an empty dict.
    """
    from unittest.mock import patch

    from amplifier_ipc.host.spawner import SpawnRequest

    registry = CapabilityRegistry()
    registry.register(
        "foundation",
        {
            "tools": [{"name": "bash", "description": "Run bash"}],
            "hooks": [{"name": "pre_tool", "event": "tool:pre", "priority": 0}],
            "orchestrators": [{"name": "loop"}],
            "context_managers": [{"name": "simple"}],
            "providers": [{"name": "anthropic"}],
            "content": [],
        },
    )

    config = SessionConfig(
        services=["foundation"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()

    host = Host(config=config, settings=settings)
    host._registry = registry
    host._persistence = None  # No persistence

    captured: list[dict] = []

    async def mock_spawn_child_session(
        parent_session_id: str,
        parent_config: dict,
        transcript: list,
        request: SpawnRequest,
        current_depth: int = 0,
    ) -> dict:
        captured.append(parent_config)
        return {
            "session_id": "child-123",
            "response": "done",
            "turn_count": 1,
            "metadata": {},
        }

    # _build_spawn_handler returns the _handle_spawn closure
    spawn_handler = host._build_spawn_handler("test-session-id")

    with patch("amplifier_ipc.host.host.spawn_child_session", mock_spawn_child_session):
        result = await spawn_handler({"agent": "explorer", "instruction": "Find files"})

    assert result["response"] == "done"
    assert len(captured) == 1
    pc = captured[0]
    # Verify actual parent_config is passed (not empty dict)
    assert pc["services"] == ["foundation"]
    assert pc["orchestrator"] == "loop"
    assert pc["context_manager"] == "simple"
    assert pc["provider"] == "anthropic"
    assert pc["component_config"] == {}
    # tools and hooks come from the registry
    assert any(t["name"] == "bash" for t in pc["tools"])
    assert any(h["name"] == "pre_tool" for h in pc["hooks"])


async def test_host_resume_handler_wired() -> None:
    """Router receives resume_handler that handles request.session_resume,
    returns response and session_id correctly.

    Verifies that _build_resume_handler builds a closure that:
    1. Loads the child session's transcript from persistence.
    2. Prepends the transcript as context lines (role: content format).
    3. Calls _run_child_session with the full instruction.
    4. Returns a result dict with response and session_id.
    5. The Router is wired with resume_handler so request.session_resume routes correctly.
    """
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    from amplifier_ipc.host.persistence import SessionPersistence

    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)

        # Create a child session with a transcript so the handler can load it
        child_session_id = "child-session-abc"
        child_persistence = SessionPersistence(child_session_id, session_dir)
        child_persistence.append_message({"role": "user", "content": "Old question"})
        child_persistence.append_message({"role": "assistant", "content": "Old answer"})

        registry = CapabilityRegistry()
        registry.register(
            "foundation",
            {
                "tools": [{"name": "bash", "description": "Run bash"}],
                "hooks": [],
                "orchestrators": [{"name": "loop"}],
                "context_managers": [{"name": "simple"}],
                "providers": [{"name": "anthropic"}],
                "content": [],
            },
        )

        config = SessionConfig(
            services=["foundation"],
            orchestrator="loop",
            context_manager="simple",
            provider="anthropic",
        )
        settings = HostSettings()

        host = Host(config=config, settings=settings, session_dir=session_dir)
        host._registry = registry
        host._services = {
            "foundation": FakeService(FakeClient()),
            "ctx": FakeService(FakeClient()),
            "provider": FakeService(FakeClient()),
        }

        captured: list[dict[str, Any]] = []

        async def mock_run_child_session(
            child_session_id: str,
            child_config: dict,
            instruction: str,
            request: Any,
            settings: Any = None,
            session_dir: Any = None,
        ) -> dict:
            captured.append(
                {
                    "child_session_id": child_session_id,
                    "instruction": instruction,
                    "child_config": child_config,
                }
            )
            return {
                "session_id": child_session_id,
                "response": "resumed response",
                "turn_count": 1,
                "metadata": {},
            }

        resume_handler = host._build_resume_handler("parent-sess-id")

        host._router = Router(
            registry=registry,
            services=host._services,
            context_manager_key="ctx",
            provider_key="provider",
            resume_handler=resume_handler,
        )

        with patch(
            "amplifier_ipc.host.host._run_child_session", mock_run_child_session
        ):
            result = await host._handle_orchestrator_request(
                "request.session_resume",
                {"session_id": child_session_id, "instruction": "Follow-up question"},
            )

        # Verify response and session_id are returned correctly
        assert result["response"] == "resumed response"
        assert result["session_id"] == child_session_id

        # Verify _run_child_session was called once with the child session id
        assert len(captured) == 1
        assert captured[0]["child_session_id"] == child_session_id

        # Verify transcript context was prepended in role: content format
        full_instruction = captured[0]["instruction"]
        assert "user: Old question" in full_instruction
        assert "assistant: Old answer" in full_instruction
        assert "Follow-up question" in full_instruction

        # Verify child_config was built from parent config
        pc = captured[0]["child_config"]
        assert pc["services"] == ["foundation"]
        assert pc["orchestrator"] == "loop"
        assert pc["context_manager"] == "simple"
        assert pc["provider"] == "anthropic"


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
        patch("amplifier_ipc.host.host.write_message", fake_write),
        patch("amplifier_ipc.host.host.read_message", fake_read),
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


async def test_host_send_approval_unblocks_loop() -> None:
    """Host yields ApprovalRequestEvent with correct params, consumer calls
    send_approval(True), loop continues to yield CompleteEvent.

    The _orchestrator_loop must block waiting for send_approval() after
    yielding the ApprovalRequestEvent.  send_approval() uses put_nowait()
    so it is non-blocking on the caller side.
    """
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
                "method": "approval_request",
                "params": {"tool_name": "bash"},
            }
        else:
            # Final response matching execute_id
            return {
                "jsonrpc": "2.0",
                "id": captured_id[0],
                "result": "done",
            }

    with (
        patch("amplifier_ipc.host.host.write_message", fake_write),
        patch("amplifier_ipc.host.host.read_message", fake_read),
    ):
        events = []
        async for event in host._orchestrator_loop(
            orchestrator_key="orch",
            prompt="hello",
            system_prompt="be helpful",
        ):
            events.append(event)
            if isinstance(event, ApprovalRequestEvent):
                # Consumer unblocks the loop by calling send_approval
                host.send_approval(True)

    assert len(events) == 2
    assert isinstance(events[0], ApprovalRequestEvent)
    assert events[0].params == {"tool_name": "bash"}
    assert isinstance(events[1], CompleteEvent)
    assert events[1].result == "done"


async def test_host_resume_loads_previous_transcript() -> None:
    """Host restores a previous session transcript when _resume_session_id is set.

    Verifies _resume_session_id is set correctly, and that _restore_from_session():
    1. Loads the previous session's transcript.
    2. Replays each message via route_request('request.context_add_message', ...).
    3. Returns the previous session ID (for reuse as the active session_id).
    4. Updates self._persistence to the previous session's persistence object.
    5. Updates self._state from the previous session's state.
    """
    import tempfile
    from pathlib import Path

    from amplifier_ipc.host.persistence import SessionPersistence

    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)

        # Create a previous session with a transcript and state
        prev_session_id = "prev-session-abc"
        prev_persistence = SessionPersistence(prev_session_id, session_dir)
        prev_persistence.append_message({"role": "user", "content": "Hello"})
        prev_persistence.append_message({"role": "assistant", "content": "Hi there!"})
        prev_persistence.save_state({"some_key": "some_value"})

        config = SessionConfig(
            services=[],
            orchestrator="loop",
            context_manager="simple",
            provider="anthropic",
        )
        settings = HostSettings()

        host = Host(config=config, settings=settings, session_dir=session_dir)

        # Verify _resume_session_id is initially None
        assert host._resume_session_id is None

        # Set it and verify it's stored correctly
        host.set_resume_session_id(prev_session_id)
        assert host._resume_session_id == prev_session_id

        # Set up a mock router that records context_add_message calls
        context_add_calls: list[dict[str, Any]] = []

        async def mock_route_request(method: str, params: Any) -> Any:
            if method == "request.context_add_message":
                context_add_calls.append(params)
            return {}

        mock_router = MagicMock()
        mock_router.route_request = mock_route_request
        host._router = mock_router

        # Call the restore method directly (this is what run() calls internally)
        returned_session_id = await host._restore_from_session()

        # Verify session ID is the resume session ID (for reuse)
        assert returned_session_id == prev_session_id

        # Verify all transcript messages were replayed via context_add_message
        assert len(context_add_calls) == 2
        assert context_add_calls[0] == {"message": {"role": "user", "content": "Hello"}}
        assert context_add_calls[1] == {
            "message": {"role": "assistant", "content": "Hi there!"}
        }

        # Verify persistence is updated to the resumed session's directory
        assert host._persistence is not None
        assert host._persistence._session_dir == session_dir / prev_session_id

        # Verify state is loaded from the resumed session
        assert host._state == {"some_key": "some_value"}


async def test_host_sends_configure_after_describe() -> None:
    """_build_registry sends configure after describe for services with service_configs.

    After calling describe on each service and registering its capabilities,
    the host should call configure with the merged service config if
    _service_configs contains an entry for that service ref.

    Services without a config entry should only receive describe (no configure).
    """
    describe_result = {
        "capabilities": {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": [],
        },
    }

    # Service that has config
    client_with_config = FakeClient(
        responses={"describe": describe_result, "configure": {}}
    )
    service_with_config = FakeService(client_with_config)

    # Service that has NO config — configure should NOT be called on it
    client_no_config = FakeClient(responses={"describe": describe_result})
    service_no_config = FakeService(client_no_config)

    config = SessionConfig(
        services=["svc-a", "svc-b"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()

    host = Host(config=config, settings=settings)
    host._services = {
        "svc-a": service_with_config,
        "svc-b": service_no_config,
    }

    # Inject service config only for "svc-a"
    service_config = {"model": "claude-3-5-sonnet", "temperature": 0.7}
    host._service_configs = {"svc-a": service_config}

    await host._build_registry()

    # svc-a: describe first, then configure with the merged config
    assert len(client_with_config.calls) == 2
    assert client_with_config.calls[0][0] == "describe"
    assert client_with_config.calls[1][0] == "configure"
    assert client_with_config.calls[1][1] == {"config": service_config}

    # svc-b: only describe (no config entry)
    assert len(client_no_config.calls) == 1
    assert client_no_config.calls[0][0] == "describe"


async def test_host_send_approval_is_non_blocking() -> None:
    """send_approval() is non-blocking (uses put_nowait under the hood)."""
    config = SessionConfig(
        services=[],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()

    host = Host(config=config, settings=settings)

    # Calling send_approval should not block or raise
    host.send_approval(True)
    host.send_approval(False)

    # Queue should have both values
    assert host._approval_queue.get_nowait() is True
    assert host._approval_queue.get_nowait() is False


async def test_host_build_registry_configure_method_not_found_is_logged_and_skipped() -> None:
    """_build_registry logs a warning and continues if configure returns METHOD_NOT_FOUND.

    Services installed from an older amplifier-ipc version may not support the
    configure protocol.  When configure raises JsonRpcError(METHOD_NOT_FOUND),
    _build_registry must log a warning and continue without raising so that the
    rest of the startup sequence can proceed.
    """
    from amplifier_ipc.protocol.errors import METHOD_NOT_FOUND, JsonRpcError

    describe_result = {
        "capabilities": {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": [],
        },
    }

    def _raise_method_not_found(_params: object) -> None:
        raise JsonRpcError(METHOD_NOT_FOUND, "Method not found: 'configure'")

    client = FakeClient(
        responses={
            "describe": describe_result,
            "configure": _raise_method_not_found,
        }
    )
    service = FakeService(client)

    config = SessionConfig(
        services=["old-svc"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    host = Host(config=config, settings=HostSettings())
    host._services = {"old-svc": service}
    host._service_configs = {"old-svc": {"key": "value"}}

    # Must not raise even though configure is not supported
    await host._build_registry()

    # describe was called
    assert any(call[0] == "describe" for call in client.calls)
    # configure was attempted
    assert any(call[0] == "configure" for call in client.calls)
