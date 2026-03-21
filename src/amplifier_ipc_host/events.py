"""Host event dataclass hierarchy.

Events are yielded by :meth:`Host.run` and :meth:`Host._orchestrator_loop`
as an async stream, replacing the previous batch-result return value.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HostEvent:
    """Base class for all host events."""


@dataclass
class StreamTokenEvent(HostEvent):
    """Emitted when the orchestrator streams a text token (stream.token)."""

    token: str = ""


@dataclass
class StreamThinkingEvent(HostEvent):
    """Emitted when the orchestrator streams a thinking fragment (stream.thinking)."""

    thinking: str = ""


@dataclass
class StreamToolCallStartEvent(HostEvent):
    """Emitted when the orchestrator starts a tool call (stream.tool_call_start)."""

    tool_name: str = ""


@dataclass
class ApprovalRequestEvent(HostEvent):
    """Emitted when the orchestrator requests user approval (approval_request)."""

    params: dict = field(default_factory=dict)  # type: ignore[type-arg]


@dataclass
class ErrorEvent(HostEvent):
    """Emitted when the orchestrator sends a non-fatal error notification (error)."""

    message: str = ""


@dataclass
class CompleteEvent(HostEvent):
    """Emitted as the final event carrying the orchestrator's full response (complete)."""

    result: str = ""
