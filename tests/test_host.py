"""Tests for the Host orchestration class."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_host.config import HostSettings, SessionConfig
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
    """_build_registry sends describe to each service and populates the registry."""
    describe_result = {
        "tools": [{"name": "bash", "description": "Run bash commands"}],
        "hooks": [],
        "orchestrators": [{"name": "loop"}],
        "context_managers": [{"name": "simple"}],
        "providers": [{"name": "anthropic"}],
        "content": [],
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
