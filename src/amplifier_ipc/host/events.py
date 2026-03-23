"""Host event model hierarchy.

Events are yielded by :meth:`Host.run` and :meth:`Host._orchestrator_loop`
as an async stream, replacing the previous batch-result return value.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HostEvent(BaseModel):
    """Base class for all host events."""


class StreamTokenEvent(HostEvent):
    """Emitted when the orchestrator streams a text token (stream.token)."""

    token: str = ""


class StreamThinkingEvent(HostEvent):
    """Emitted when the orchestrator streams a thinking fragment (stream.thinking)."""

    thinking: str = ""


class StreamToolCallStartEvent(HostEvent):
    """Emitted when the orchestrator starts a tool call (stream.tool_call_start)."""

    tool_name: str = ""


class StreamContentBlockStartEvent(HostEvent):
    """Emitted when the provider starts a new content block (stream.content_block_start)."""

    block_type: str = ""
    index: int = 0


class StreamContentBlockEndEvent(HostEvent):
    """Emitted when the provider ends a content block (stream.content_block_end)."""

    block_type: str = ""
    index: int = 0


class ApprovalRequestEvent(HostEvent):
    """Emitted when the orchestrator requests user approval (approval_request)."""

    params: dict[str, Any] = Field(default_factory=dict)


class ErrorEvent(HostEvent):
    """Emitted when the orchestrator sends a non-fatal error notification (error)."""

    message: str = ""


class CompleteEvent(HostEvent):
    """Emitted as the final event carrying the orchestrator's full response (complete)."""

    result: str = ""


class ToolCallEvent(HostEvent):
    """Emitted when a tool call is dispatched."""

    tool_name: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResultEvent(HostEvent):
    """Emitted when a tool call result is received."""

    tool_name: str = ""
    success: bool = True
    output: str = ""


class TodoUpdateEvent(HostEvent):
    """Emitted when the todo list is updated."""

    todos: list[dict[str, Any]] = Field(default_factory=list)
    status: str = ""


class ChildSessionStartEvent(HostEvent):
    """Emitted when a child session is started."""

    agent_name: str = ""
    session_id: str = ""
    depth: int = 1


class ChildSessionEndEvent(HostEvent):
    """Emitted when a child session ends."""

    session_id: str = ""
    depth: int = 1


class ChildSessionEvent(HostEvent):
    """Wraps an event emitted by a child session, carrying the nesting depth."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    depth: int = 1
    inner: HostEvent | None = None
