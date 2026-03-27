"""Tests for Host._emit_hook_event(), parent_session_id, and session:start event emission."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amplifier_ipc.host.config import HostSettings, SessionConfig
from amplifier_ipc.host.host import Host
from amplifier_ipc.host.service_index import ServiceIndex
from amplifier_ipc_protocol.events import (
    CANCEL_COMPLETED,  # noqa: F401
    CANCEL_REQUESTED,  # noqa: F401
    SESSION_END,
    SESSION_FORK,
    SESSION_RESUME,  # noqa: F401
    SESSION_START,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_host() -> Host:
    """Create a Host with minimal config for testing."""
    config = SessionConfig(
        services=["svc"],
        orchestrator="streaming",
        context_manager="simple",
        provider="anthropic",
    )
    return Host(config=config, settings=HostSettings())


class FakeClient:
    """Records calls and returns canned responses."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._responses: dict[str, Any] = responses or {}
        self._read_task: Any = None

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


def _make_host_with_registry(
    parent_session_id: str | None = None,
    session_dir: Path | None = None,
) -> Host:
    """Create a Host with a pre-populated ServiceIndex and fake services.

    Uses shared_services to prevent Host from trying to spawn real processes.
    Passes shared_registry so the registry is already populated.
    """
    config = SessionConfig(
        services=["svc"],
        orchestrator="streaming",
        context_manager="simple",
        provider="anthropic",
    )

    registry = ServiceIndex()
    registry.register(
        "svc",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [{"name": "streaming"}],
            "context_managers": [{"name": "simple"}],
            "providers": [{"name": "anthropic"}],
            "content": [],
        },
    )

    shared_services: dict[str, Any] = {"svc": FakeService(FakeClient())}

    return Host(
        config=config,
        settings=HostSettings(),
        session_dir=session_dir,
        shared_services=shared_services,
        shared_registry=registry,
        parent_session_id=parent_session_id,
    )


async def _drain(host: Host) -> list[tuple[str, dict[str, Any]]]:
    """Run host.run() with mocked internals and capture _emit_hook_event calls.

    Patches:
    - _emit_hook_event to capture (event_name, data) tuples
    - _orchestrator_loop to a no-op async generator
    - assemble_system_prompt to return 'system prompt'

    Returns a list of (event_name, data) tuples from captured emit calls.
    """
    captured: list[tuple[str, dict[str, Any]]] = []

    async def capture_emit(event_name: str, data: dict[str, Any]) -> None:
        captured.append((event_name, data))

    async def noop_orchestrator_loop(*args: Any, **kwargs: Any) -> Any:
        return  # return before yield makes this a no-op async generator
        yield  # noqa: unreachable

    with (
        patch.object(host, "_emit_hook_event", capture_emit),
        patch.object(host, "_orchestrator_loop", noop_orchestrator_loop),
        patch(
            "amplifier_ipc.host.host.assemble_system_prompt",
            AsyncMock(return_value="system prompt"),
        ),
    ):
        async for _ in host.run("hello"):
            pass

    return captured


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_hook_event_dispatches_to_router() -> None:
    """_emit_hook_event calls router.route_request with correct method and params."""
    host = _make_host()

    # Inject a mock router
    mock_router = MagicMock()
    mock_router.route_request = AsyncMock(return_value={"ok": True})
    host._router = mock_router

    await host._emit_hook_event("session.start", {"key": "value"})

    mock_router.route_request.assert_called_once_with(
        "request.hook_emit",
        {"event": "session.start", "data": {"key": "value"}},
    )


@pytest.mark.asyncio
async def test_emit_hook_event_swallows_exceptions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_emit_hook_event catches exceptions from router and does not propagate them."""
    host = _make_host()

    # Inject a mock router that raises
    mock_router = MagicMock()
    mock_router.route_request = AsyncMock(side_effect=RuntimeError("router exploded"))
    host._router = mock_router

    # Should not raise — errors must be swallowed
    with caplog.at_level(logging.ERROR):
        await host._emit_hook_event("session.end", {})

    # Router was still called
    mock_router.route_request.assert_called_once()

    # Exception was logged (not silently discarded)
    assert "Failed to emit hook event" in caplog.text


@pytest.mark.asyncio
async def test_emit_hook_event_noop_without_router() -> None:
    """_emit_hook_event is a no-op when _router is None."""
    host = _make_host()

    assert host._router is None

    # Should not raise and should not attempt any routing
    await host._emit_hook_event("session.start", {"foo": "bar"})


@pytest.mark.asyncio
async def test_run_emits_session_start(tmp_path: Path) -> None:
    """Host.run() emits SESSION_START with correct session_id, parent_id, and raw config."""
    host = _make_host_with_registry(session_dir=tmp_path)

    calls = await _drain(host)

    # Exactly one session:start event
    start_calls = [(evt, data) for evt, data in calls if evt == SESSION_START]
    assert len(start_calls) == 1, (
        f"Expected 1 session:start call, got {len(start_calls)}"
    )

    _, payload = start_calls[0]

    # session_id must match the host's assigned session_id
    assert payload["session_id"] == host._session_id
    assert payload["session_id"] is not None

    # No parent — parent_id should be None
    assert payload["parent_id"] is None

    # raw config must contain provider and orchestrator from SessionConfig
    raw = payload["raw"]
    assert raw["provider"] == "anthropic"
    assert raw["orchestrator"] == "streaming"


@pytest.mark.asyncio
async def test_run_session_start_includes_parent_id(tmp_path: Path) -> None:
    """Host.run() includes parent_id='parent-123' in SESSION_START payload."""
    host = _make_host_with_registry(
        parent_session_id="parent-123",
        session_dir=tmp_path,
    )

    calls = await _drain(host)

    start_calls = [(evt, data) for evt, data in calls if evt == SESSION_START]
    assert len(start_calls) == 1, (
        f"Expected 1 session:start call, got {len(start_calls)}"
    )

    _, payload = start_calls[0]
    assert payload["parent_id"] == "parent-123"


@pytest.mark.asyncio
async def test_run_emits_session_end_completed(tmp_path: Path) -> None:
    """Host.run() emits SESSION_END with status='completed' on normal exit."""
    host = _make_host_with_registry(session_dir=tmp_path)

    calls = await _drain(host)

    end_calls = [(evt, data) for evt, data in calls if evt == SESSION_END]
    assert len(end_calls) == 1, f"Expected 1 session:end call, got {len(end_calls)}"

    _, payload = end_calls[0]
    assert payload["session_id"] == host._session_id
    assert payload["status"] == "completed"


@pytest.mark.asyncio
async def test_run_emits_session_end_failed(tmp_path: Path) -> None:
    """Host.run() emits SESSION_END with status='failed' when orchestrator raises RuntimeError."""
    host = _make_host_with_registry(session_dir=tmp_path)

    captured: list[tuple[str, dict[str, Any]]] = []

    async def capture_emit(event_name: str, data: dict[str, Any]) -> None:
        captured.append((event_name, data))

    async def exploding_loop(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("orchestrator exploded")
        yield  # type: ignore[misc]  # noqa: unreachable

    with (
        patch.object(host, "_emit_hook_event", capture_emit),
        patch.object(host, "_orchestrator_loop", exploding_loop),
        patch(
            "amplifier_ipc.host.host.assemble_system_prompt",
            AsyncMock(return_value="system prompt"),
        ),
        pytest.raises(RuntimeError, match="orchestrator exploded"),
    ):
        async for _ in host.run("hello"):
            pass

    end_calls = [(evt, data) for evt, data in captured if evt == SESSION_END]
    assert len(end_calls) == 1, f"Expected 1 session:end call, got {len(end_calls)}"

    _, payload = end_calls[0]
    assert payload["status"] == "failed"


@pytest.mark.asyncio
async def test_run_emits_session_end_cancelled(tmp_path: Path) -> None:
    """Host.run() emits SESSION_END with status='cancelled' when CancelledError is raised."""
    host = _make_host_with_registry(session_dir=tmp_path)

    captured: list[tuple[str, dict[str, Any]]] = []

    async def capture_emit(event_name: str, data: dict[str, Any]) -> None:
        captured.append((event_name, data))

    async def cancelled_loop(*args: Any, **kwargs: Any) -> Any:
        raise asyncio.CancelledError()
        yield  # type: ignore[misc]  # noqa: unreachable

    with (
        patch.object(host, "_emit_hook_event", capture_emit),
        patch.object(host, "_orchestrator_loop", cancelled_loop),
        patch(
            "amplifier_ipc.host.host.assemble_system_prompt",
            AsyncMock(return_value="system prompt"),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        async for _ in host.run("hello"):
            pass

    end_calls = [(evt, data) for evt, data in captured if evt == SESSION_END]
    assert len(end_calls) == 1, f"Expected 1 session:end call, got {len(end_calls)}"

    _, payload = end_calls[0]
    assert payload["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Phase 3 — session:fork
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_spawn_emits_session_fork(tmp_path: Path) -> None:
    """_handle_spawn emits SESSION_FORK with child_session_id, parent, and agent."""
    host = _make_host_with_registry(session_dir=tmp_path)
    host._session_id = "parent-abc"

    # Build the spawn handler with a known parent session_id
    handler = host._build_spawn_handler("parent-abc", current_depth=0)

    # Track _emit_hook_event calls
    emitted: list[tuple[str, dict[str, Any]]] = []

    async def capture_emit(event_name: str, data: dict[str, Any]) -> None:
        emitted.append((event_name, data))

    host._emit_hook_event = capture_emit  # type: ignore[assignment]

    # Mock spawn_child_session to avoid real subprocess spawning
    with patch(
        "amplifier_ipc.host.host.spawn_child_session",
        new_callable=AsyncMock,
        return_value="child result",
    ):
        result = await handler({"agent": "code-review", "instruction": "review this"})

    assert result == "child result"

    # Verify session:fork was emitted
    fork_events = [(e, d) for e, d in emitted if e == SESSION_FORK]
    assert len(fork_events) == 1, f"Expected 1 session:fork, got {len(fork_events)}"

    data = fork_events[0][1]
    assert data["parent_id"] == "parent-abc"
    assert "session_id" in data  # child_session_id is generated
    assert data["agent"] == "code-review"


# ---------------------------------------------------------------------------
# Phase 3 — session:resume (top-level, Pattern A)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_emits_session_resume_instead_of_start(tmp_path: Path) -> None:
    """When resuming, Host.run() emits SESSION_RESUME instead of SESSION_START."""
    host = _make_host_with_registry(session_dir=tmp_path)

    # Simulate a resume by setting _resume_session_id
    host._resume_session_id = "prev-session-999"

    # Capture events, but also need to mock _restore_from_session
    captured: list[tuple[str, dict[str, Any]]] = []

    async def capture_emit(event_name: str, data: dict[str, Any]) -> None:
        captured.append((event_name, data))

    async def noop_orchestrator_loop(*args: Any, **kwargs: Any) -> Any:
        return
        yield  # type: ignore[misc]  # noqa: unreachable

    async def fake_restore() -> str:
        return "prev-session-999"

    with (
        patch.object(host, "_emit_hook_event", capture_emit),
        patch.object(host, "_orchestrator_loop", noop_orchestrator_loop),
        patch.object(host, "_restore_from_session", fake_restore),
        patch(
            "amplifier_ipc.host.host.assemble_system_prompt",
            AsyncMock(return_value="system prompt"),
        ),
    ):
        async for _ in host.run("continue"):
            pass

    # SESSION_RESUME should be present, SESSION_START should NOT
    resume_events = [(e, d) for e, d in captured if e == SESSION_RESUME]
    start_events = [(e, d) for e, d in captured if e == SESSION_START]

    assert len(resume_events) == 1, (
        f"Expected 1 session:resume, got {len(resume_events)}"
    )
    assert len(start_events) == 0, (
        f"Expected 0 session:start when resuming, got {len(start_events)}"
    )

    data = resume_events[0][1]
    assert data["session_id"] is not None
    assert data["parent_id"] == host._parent_session_id
    assert "raw" in data
