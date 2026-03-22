"""typing.Protocol classes defining component interface contracts.

All protocols are @runtime_checkable to support isinstance() checks.
Uses structural subtyping (duck typing), NOT ABC inheritance.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from amplifier_ipc_protocol.models import (
    ChatRequest,
    ChatResponse,
    HookResult,
    Message,
    ToolResult,
)


@runtime_checkable
class ToolProtocol(Protocol):
    """Interface contract for tool components."""

    name: str
    description: str
    input_schema: dict[str, Any]

    async def execute(self, input: dict[str, Any]) -> ToolResult: ...


@runtime_checkable
class HookProtocol(Protocol):
    """Interface contract for hook components."""

    name: str
    events: list[str]
    priority: int

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult: ...


@runtime_checkable
class OrchestratorProtocol(Protocol):
    """Interface contract for orchestrator components."""

    name: str

    async def execute(
        self, prompt: str, config: dict[str, Any], client: Any
    ) -> str: ...


@runtime_checkable
class ContextManagerProtocol(Protocol):
    """Interface contract for context manager components."""

    name: str

    async def add_message(self, message: Message) -> None: ...

    async def get_messages(self, provider_info: dict[str, Any]) -> list[Message]: ...

    async def clear(self) -> None: ...


@runtime_checkable
class ProviderProtocol(Protocol):
    """Interface contract for provider components."""

    name: str

    async def complete(self, request: ChatRequest) -> ChatResponse: ...
