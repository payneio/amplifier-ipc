"""Host event model hierarchy.

Events are yielded by :meth:`Host.run` and :meth:`Host._orchestrator_loop`
as an async stream, replacing the previous batch-result return value.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
