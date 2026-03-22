"""Pydantic v2 wire-format data models for amplifier-ipc-protocol.

Ported from amplifier-lite's models.py. All models round-trip cleanly through
model_dump(mode='json') -> json.dumps -> json.loads -> model_validate.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ToolCall(BaseModel):
    """Tool call from an LLM response.

    Accepts ``"tool"`` as an alias for ``name`` because the real orchestrator
    serialises tool calls as ``{"id": ..., "tool": ..., "arguments": ...}``.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    name: str = Field(
        default="",
        validation_alias=AliasChoices("name", "tool"),
        serialization_alias="tool",
    )
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolSpec(BaseModel):
    """Tool specification for LLM function calling."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Tool execution result."""

    model_config = ConfigDict(extra="allow")

    success: bool = True
    output: Any = None
    error: dict[str, Any] | None = None

    def get_serialized_output(self) -> str:
        """Serialize the result for inclusion in conversation context."""
        if self.output is not None:
            if isinstance(self.output, (dict, list)):
                return json.dumps(self.output)
            return str(self.output)
        return ""


class Message(BaseModel):
    """Chat message with flexible content (str or list of content blocks)."""

    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] | None = None
    thinking_block: dict[str, Any] | None = None


class HookAction(str, Enum):
    """Actions a hook can take in response to an event."""

    CONTINUE = "CONTINUE"
    DENY = "DENY"
    MODIFY = "MODIFY"
    INJECT_CONTEXT = "INJECT_CONTEXT"
    ASK_USER = "ASK_USER"


class HookResult(BaseModel):
    """Result returned by a hook handler."""

    model_config = ConfigDict(extra="allow")

    action: HookAction = HookAction.CONTINUE
    data: dict[str, Any] | None = None
    reason: str | None = None
    message: Message | None = None
    question: str | None = None
    injected_messages: list[Message] = Field(default_factory=list)
    # Context injection fields
    ephemeral: bool = False
    context_injection: str | None = None
    context_injection_role: str = "user"
    append_to_last_tool_result: bool = False
    # Output control fields
    suppress_output: bool = False
    user_message: str | None = None
    user_message_level: str = "info"
    user_message_source: str | None = None
    # Approval gate fields
    approval_prompt: str | None = None
    approval_options: list[str] | None = None
    approval_timeout: float = 300.0
    approval_default: str = "deny"


class ChatRequest(BaseModel):
    """Request payload for a chat completion."""

    model_config = ConfigDict(extra="allow")

    messages: list[Message]
    tools: list[ToolSpec] | None = None
    system: str | None = None
    reasoning_effort: str | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    response_format: Any | None = None


class ChatResponse(BaseModel):
    """Response from a chat completion."""

    model_config = ConfigDict(extra="allow")

    content: str | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    text: str | None = None
    usage: Any | None = None
    content_blocks: list[Any] | None = None
    metadata: dict[str, Any] | None = None
    finish_reason: str | None = None


class TextBlock(BaseModel):
    """Regular text content (Pydantic variant for provider compat)."""

    model_config = ConfigDict(extra="allow")

    type: str = "text"
    text: str = ""
    visibility: str | None = None


class ThinkingBlock(BaseModel):
    """Model reasoning/thinking content (Pydantic variant for provider compat)."""

    model_config = ConfigDict(extra="allow")

    type: str = "thinking"
    thinking: str = ""
    signature: str | None = None
    visibility: str | None = None
    content: list[Any] | None = None


class ToolCallBlock(BaseModel):
    """Tool call request from model (Pydantic variant for provider compat)."""

    model_config = ConfigDict(extra="allow")

    type: str = "tool_call"
    id: str = ""
    name: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    visibility: str | None = None


class Usage(BaseModel):
    """Token usage information from provider responses."""

    model_config = ConfigDict(extra="allow")

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
