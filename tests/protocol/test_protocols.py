"""Tests for typing.Protocol component interface contracts."""

from __future__ import annotations

from typing import Any


from amplifier_ipc.protocol.models import (
    ChatRequest,
    ChatResponse,
    HookResult,
    Message,
    ToolResult,
)
from amplifier_ipc.protocol.protocols import (
    ContextManagerProtocol,
    HookProtocol,
    OrchestratorProtocol,
    ProviderProtocol,
    ToolProtocol,
)


# ---------------------------------------------------------------------------
# Concrete classes that satisfy each protocol
# ---------------------------------------------------------------------------


class ConcreteToolProtocol:
    name: str = "my_tool"
    description: str = "A test tool"
    input_schema: dict[str, Any] = {}

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True)


class ConcreteHookProtocol:
    name: str = "my_hook"
    events: list[str] = ["before_execute"]
    priority: int = 10

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        return HookResult()


class ConcreteOrchestratorProtocol:
    name: str = "my_orchestrator"

    async def execute(self, prompt: str, config: dict[str, Any], client: Any) -> str:
        return "result"


class ConcreteContextManagerProtocol:
    name: str = "my_context_manager"

    async def add_message(self, message: Message) -> None:
        pass

    async def get_messages(self, provider_info: dict[str, Any]) -> list[Message]:
        return []

    async def clear(self) -> None:
        pass


class ConcreteProviderProtocol:
    name: str = "my_provider"

    async def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse()


# ---------------------------------------------------------------------------
# Incomplete class — missing required methods/attributes
# ---------------------------------------------------------------------------


class IncompleteToolProtocol:
    """Missing execute method — should NOT satisfy ToolProtocol."""

    name: str = "incomplete"
    description: str = "Missing execute"
    # input_schema is missing


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_tool_protocol_satisfied():
    """A class with the right shape satisfies ToolProtocol isinstance check."""
    obj = ConcreteToolProtocol()
    assert isinstance(obj, ToolProtocol)


def test_hook_protocol_satisfied():
    """A class with the right shape satisfies HookProtocol isinstance check."""
    obj = ConcreteHookProtocol()
    assert isinstance(obj, HookProtocol)


def test_orchestrator_protocol_satisfied():
    """A class with the right shape satisfies OrchestratorProtocol isinstance check."""
    obj = ConcreteOrchestratorProtocol()
    assert isinstance(obj, OrchestratorProtocol)


def test_context_manager_protocol_satisfied():
    """A class with the right shape satisfies ContextManagerProtocol isinstance check."""
    obj = ConcreteContextManagerProtocol()
    assert isinstance(obj, ContextManagerProtocol)


def test_provider_protocol_satisfied():
    """A class with the right shape satisfies ProviderProtocol isinstance check."""
    obj = ConcreteProviderProtocol()
    assert isinstance(obj, ProviderProtocol)


def test_all_protocols_are_runtime_checkable():
    """All protocols have __protocol_attrs__ (runtime_checkable marker)."""
    for protocol in (
        ToolProtocol,
        HookProtocol,
        OrchestratorProtocol,
        ContextManagerProtocol,
        ProviderProtocol,
    ):
        assert hasattr(protocol, "__protocol_attrs__"), (
            f"{protocol.__name__} is not @runtime_checkable"
        )


def test_incomplete_class_does_not_satisfy_tool_protocol():
    """A class missing required attributes does NOT satisfy ToolProtocol."""
    obj = IncompleteToolProtocol()
    assert not isinstance(obj, ToolProtocol)
