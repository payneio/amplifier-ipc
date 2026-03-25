"""Unit tests for Host._emit_hook_event() and parent_session_id parameter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_ipc.host.config import HostSettings, SessionConfig
from amplifier_ipc.host.host import Host


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
async def test_emit_hook_event_swallows_exceptions() -> None:
    """_emit_hook_event catches exceptions from router and does not propagate them."""
    host = _make_host()

    # Inject a mock router that raises
    mock_router = MagicMock()
    mock_router.route_request = AsyncMock(side_effect=RuntimeError("router exploded"))
    host._router = mock_router

    # Should not raise — errors must be swallowed
    await host._emit_hook_event("session.end", {})

    # Router was still called
    mock_router.route_request.assert_called_once()


@pytest.mark.asyncio
async def test_emit_hook_event_noop_without_router() -> None:
    """_emit_hook_event is a no-op when _router is None."""
    host = _make_host()

    assert host._router is None

    # Should not raise and should not attempt any routing
    await host._emit_hook_event("session.start", {"foo": "bar"})
