"""Tests for message router module."""

from __future__ import annotations

from typing import Any

import pytest

from amplifier_ipc_host.registry import CapabilityRegistry
from amplifier_ipc_host.router import Router
from amplifier_ipc_protocol.errors import INVALID_PARAMS, METHOD_NOT_FOUND, JsonRpcError


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClient:
    """Records calls and returns canned responses."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._responses: dict[str, Any] = responses or {}

    async def request(self, method: str, params: Any = None) -> Any:
        self.calls.append((method, params))
        if method in self._responses:
            return self._responses[method]
        return {}


class FakeService:
    """A minimal service stub with a FakeClient."""

    def __init__(self, client: FakeClient) -> None:
        self.client = client


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _build_router_with_two_services(
    foundation_responses: dict[str, Any] | None = None,
    provider_responses: dict[str, Any] | None = None,
) -> tuple[Router, FakeClient, FakeClient]:
    """Build a Router with foundation (tool:bash, hook:approval) and providers services."""
    registry = CapabilityRegistry()
    registry.register(
        "foundation",
        {
            "tools": [{"name": "bash", "description": "Run bash commands"}],
            "hooks": [{"name": "approval", "event": "tool:pre", "priority": 10}],
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
            "providers": [{"name": "anthropic"}],
            "content": [],
        },
    )

    foundation_client = FakeClient(responses=foundation_responses or {})
    provider_client = FakeClient(responses=provider_responses or {})

    services: dict[str, Any] = {
        "foundation": FakeService(foundation_client),
        "providers": FakeService(provider_client),
    }

    router = Router(
        registry=registry,
        services=services,
        context_manager_key="foundation",
        provider_key="providers",
    )

    return router, foundation_client, provider_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_route_tool_execute() -> None:
    """bash routes to foundation service, returns tool result."""
    router, foundation_client, _ = _build_router_with_two_services(
        foundation_responses={"tool.execute": {"output": "hello world"}}
    )

    result = await router.route_request(
        "request.tool_execute",
        {"tool_name": "bash", "arguments": {"command": "echo hello"}},
    )

    assert result == {"output": "hello world"}
    assert len(foundation_client.calls) == 1
    method, params = foundation_client.calls[0]
    assert method == "tool.execute"
    assert params["tool_name"] == "bash"


async def test_route_tool_execute_unknown_tool() -> None:
    """Raises JsonRpcError with INVALID_PARAMS for unknown tool."""
    router, _, _ = _build_router_with_two_services()

    with pytest.raises(JsonRpcError) as exc_info:
        await router.route_request(
            "request.tool_execute",
            {"tool_name": "nonexistent", "arguments": {}},
        )

    assert exc_info.value.code == INVALID_PARAMS
    assert "Unknown tool" in exc_info.value.message


async def test_route_hook_emit() -> None:
    """tool:pre event calls foundation hook.emit."""
    router, foundation_client, _ = _build_router_with_two_services(
        foundation_responses={"hook.emit": {"action": "CONTINUE"}}
    )

    result = await router.route_request(
        "request.hook_emit",
        {"event": "tool:pre", "data": {"tool": "bash"}},
    )

    assert result == {"action": "CONTINUE"}
    assert len(foundation_client.calls) == 1
    method, params = foundation_client.calls[0]
    assert method == "hook.emit"
    assert params["event"] == "tool:pre"
    assert params["data"] == {"tool": "bash"}


async def test_route_hook_emit_no_hooks() -> None:
    """Unknown event returns {"action": "CONTINUE"} without any service calls."""
    router, foundation_client, _ = _build_router_with_two_services()

    result = await router.route_request(
        "request.hook_emit",
        {"event": "unknown:event", "data": {}},
    )

    assert result == {"action": "CONTINUE"}
    assert len(foundation_client.calls) == 0


async def test_route_context_add_message() -> None:
    """context_add_message routes to context manager service."""
    router, foundation_client, _ = _build_router_with_two_services(
        foundation_responses={"context.add_message": None}
    )

    params = {"role": "user", "content": "Hello"}
    await router.route_request("request.context_add_message", params)

    assert len(foundation_client.calls) == 1
    method, call_params = foundation_client.calls[0]
    assert method == "context.add_message"
    assert call_params == params


async def test_route_context_get_messages() -> None:
    """context_get_messages routes to context manager service."""
    messages = [{"role": "user", "content": "Hello"}]
    router, foundation_client, _ = _build_router_with_two_services(
        foundation_responses={"context.get_messages": messages}
    )

    result = await router.route_request("request.context_get_messages", {})

    assert result == messages
    assert len(foundation_client.calls) == 1
    method, _ = foundation_client.calls[0]
    assert method == "context.get_messages"


async def test_route_context_clear() -> None:
    """context_clear routes to context manager service."""
    router, foundation_client, _ = _build_router_with_two_services(
        foundation_responses={"context.clear": None}
    )

    await router.route_request("request.context_clear", {})

    assert len(foundation_client.calls) == 1
    method, _ = foundation_client.calls[0]
    assert method == "context.clear"


async def test_route_provider_complete() -> None:
    """provider_complete routes to provider service."""
    completion = {"content": "Hello from AI"}
    router, _, provider_client = _build_router_with_two_services(
        provider_responses={"provider.complete": completion}
    )

    params = {"messages": [{"role": "user", "content": "Hello"}]}
    result = await router.route_request("request.provider_complete", params)

    assert result == completion
    assert len(provider_client.calls) == 1
    method, call_params = provider_client.calls[0]
    assert method == "provider.complete"
    # params may contain extra fields (e.g. provider name injected by router)
    assert call_params.get("messages") == params["messages"]


async def test_route_provider_complete_includes_provider_name() -> None:
    """router injects configured provider_name into provider.complete params.

    When the Router is constructed with a provider_name, that name is included
    in the params forwarded to the provider service so it can select the correct
    backend (e.g. 'anthropic' vs 'openai' vs 'azure_openai').
    """
    completion = {"content": "Hello from Anthropic"}
    registry = CapabilityRegistry()
    registry.register(
        "providers",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [{"name": "anthropic"}],
            "content": [],
        },
    )
    provider_client = FakeClient(responses={"provider.complete": completion})
    services: dict[str, Any] = {
        "foundation": FakeService(FakeClient(responses={})),
        "providers": FakeService(provider_client),
    }
    router = Router(
        registry=registry,
        services=services,
        context_manager_key="foundation",
        provider_key="providers",
        provider_name="anthropic",
    )

    params = {"request": {"messages": []}}
    result = await router.route_request("request.provider_complete", params)

    assert result == completion
    assert len(provider_client.calls) == 1
    _, call_params = provider_client.calls[0]
    # The router must inject the provider name so the service selects the right backend.
    assert call_params.get("provider") == "anthropic"


async def test_route_provider_complete_with_content_blocks() -> None:
    """provider_complete relays the full provider response including streamed content blocks."""
    # Provider returns a response that includes content block data (streaming provider pattern)
    completion = {
        "content": "Hello from AI",
        "content_blocks": [
            {"type": "text", "index": 0, "text": "Hello from AI"},
        ],
    }
    router, _, provider_client = _build_router_with_two_services(
        provider_responses={"provider.complete": completion}
    )

    params = {
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True,
    }
    result = await router.route_request("request.provider_complete", params)

    # Router relays the full response unchanged
    assert result == completion
    # Provider service received exactly one call
    assert len(provider_client.calls) == 1
    method, call_params = provider_client.calls[0]
    assert method == "provider.complete"
    # All params forwarded to provider unchanged
    assert call_params == params


async def test_route_unknown_method() -> None:
    """Raises JsonRpcError with METHOD_NOT_FOUND for unknown methods."""
    router, _, _ = _build_router_with_two_services()

    with pytest.raises(JsonRpcError) as exc_info:
        await router.route_request("request.unknown_method", {})

    assert exc_info.value.code == METHOD_NOT_FOUND
    assert "Unknown routing method" in exc_info.value.message


async def test_hook_fanout_deny_short_circuits() -> None:
    """DENY from first hook prevents second hook from being called."""
    registry = CapabilityRegistry()
    registry.register(
        "service_a",
        {
            "tools": [],
            "hooks": [{"name": "hook_a", "event": "tool:pre", "priority": 10}],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": [],
        },
    )
    registry.register(
        "service_b",
        {
            "tools": [],
            "hooks": [{"name": "hook_b", "event": "tool:pre", "priority": 20}],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": [],
        },
    )

    client_a = FakeClient(responses={"hook.emit": {"action": "DENY"}})
    client_b = FakeClient(responses={"hook.emit": {"action": "CONTINUE"}})

    services: dict[str, Any] = {
        "service_a": FakeService(client_a),
        "service_b": FakeService(client_b),
        "ctx": FakeService(FakeClient()),
        "provider": FakeService(FakeClient()),
    }

    router = Router(
        registry=registry,
        services=services,
        context_manager_key="ctx",
        provider_key="provider",
    )

    result = await router.route_request(
        "request.hook_emit",
        {"event": "tool:pre", "data": {"tool": "bash"}},
    )

    assert result == {"action": "DENY"}
    assert len(client_a.calls) == 1
    assert len(client_b.calls) == 0  # Short-circuited!


async def test_route_state_get_returns_value() -> None:
    """state_get returns the stored value for an existing key."""
    router, _, _ = _build_router_with_two_services()
    router._state = {"my_key": "my_value"}

    result = await router.route_request("request.state_get", {"key": "my_key"})

    assert result == {"value": "my_value"}


async def test_route_state_get_missing_key_returns_null() -> None:
    """state_get returns {"value": None} when the key does not exist."""
    router, _, _ = _build_router_with_two_services()
    router._state = {}

    result = await router.route_request("request.state_get", {"key": "nonexistent"})

    assert result == {"value": None}


async def test_route_state_set_stores_value() -> None:
    """state_set stores the value in state and returns {"ok": True}."""
    router, _, _ = _build_router_with_two_services()
    router._state = {}

    result = await router.route_request(
        "request.state_set", {"key": "counter", "value": 42}
    )

    assert result == {"ok": True}
    assert router._state["counter"] == 42


async def test_route_state_set_overwrites_existing() -> None:
    """state_set replaces a pre-existing value for the same key."""
    router, _, _ = _build_router_with_two_services()
    router._state = {"counter": 1}

    await router.route_request("request.state_set", {"key": "counter", "value": 99})

    assert router._state["counter"] == 99


# ---------------------------------------------------------------------------
# Sub-session spawning routing tests
# ---------------------------------------------------------------------------


async def test_route_session_spawn() -> None:
    """request.session_spawn is routed to the spawn handler."""
    router, _, _ = _build_router_with_two_services()

    spawn_result = {
        "session_id": "parent-child1_explorer",
        "response": "Done",
        "turn_count": 1,
        "metadata": {},
    }

    async def mock_spawn_handler(params: Any) -> Any:
        return spawn_result

    router._spawn_handler = mock_spawn_handler

    result = await router.route_request(
        "request.session_spawn",
        {
            "agent": "explorer",
            "instruction": "Find files",
            "context_depth": "none",
        },
    )

    assert result == spawn_result


async def test_route_session_resume() -> None:
    """request.session_resume is routed to the resume handler."""
    router, _, _ = _build_router_with_two_services()

    resume_result = {
        "session_id": "parent-child1_explorer",
        "response": "Continued",
        "turn_count": 2,
        "metadata": {},
    }

    async def mock_resume_handler(params: Any) -> Any:
        return resume_result

    router._resume_handler = mock_resume_handler

    result = await router.route_request(
        "request.session_resume",
        {
            "session_id": "parent-child1_explorer",
            "instruction": "Continue",
        },
    )

    assert result == resume_result


async def test_route_session_spawn_no_handler_raises() -> None:
    """request.session_spawn raises METHOD_NOT_FOUND when no handler configured."""
    router, _, _ = _build_router_with_two_services()

    with pytest.raises(JsonRpcError) as exc_info:
        await router.route_request("request.session_spawn", {"agent": "explorer"})

    assert exc_info.value.code == METHOD_NOT_FOUND


async def test_route_session_resume_no_handler_raises() -> None:
    """request.session_resume raises METHOD_NOT_FOUND when no handler configured."""
    router, _, _ = _build_router_with_two_services()

    with pytest.raises(JsonRpcError) as exc_info:
        await router.route_request(
            "request.session_resume", {"session_id": "old-session"}
        )

    assert exc_info.value.code == METHOD_NOT_FOUND


async def test_provider_streaming_notifications_relayed() -> None:
    """Router accepts on_provider_notification and installs/restores it on the provider client."""

    def notification_callback(msg: dict) -> None:
        pass

    class FakeClientWithNotification(FakeClient):
        """FakeClient that tracks notification callback installed during request."""

        def __init__(self, responses: dict[str, Any] | None = None) -> None:
            super().__init__(responses)
            self.on_notification: Any = None
            self.notification_during_call: Any = None

        async def request(self, method: str, params: Any = None) -> Any:
            # Capture the callback that was installed when the request was made
            self.notification_during_call = self.on_notification
            return await super().request(method, params)

    registry = CapabilityRegistry()
    registry.register(
        "providers",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [{"name": "anthropic"}],
            "content": [],
        },
    )

    provider_client = FakeClientWithNotification(
        responses={"provider.complete": {"content": "Hello"}}
    )

    services: dict[str, Any] = {
        "providers": FakeService(provider_client),
    }

    router = Router(
        registry=registry,
        services=services,
        context_manager_key="providers",
        provider_key="providers",
        on_provider_notification=notification_callback,
    )

    # Verify callback is stored
    assert router._on_provider_notification is notification_callback

    # Call provider_complete
    result = await router.route_request(
        "request.provider_complete",
        {"messages": [{"role": "user", "content": "Hello"}]},
    )

    assert result == {"content": "Hello"}
    # The callback was installed on the client during the request
    assert provider_client.notification_during_call is notification_callback
    # After the call, the callback is restored to None (previous value)
    assert provider_client.on_notification is None
