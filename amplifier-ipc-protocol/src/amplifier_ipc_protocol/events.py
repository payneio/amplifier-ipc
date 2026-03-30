"""Canonical event name constants for the Amplifier IPC protocol.

This module is the single source of truth for all 41 event constant strings.
Names match the amplifier_core.events module for compatibility.

All values follow the ``namespace:action`` convention where both namespace
and action are lowercase with underscores preserved (e.g. ``content_block:start``).
"""

# Session Lifecycle
SESSION_START: str = "session:start"
SESSION_END: str = "session:end"
SESSION_FORK: str = "session:fork"
SESSION_RESUME: str = "session:resume"

# Prompt
PROMPT_SUBMIT: str = "prompt:submit"
PROMPT_COMPLETE: str = "prompt:complete"

# Planning
PLAN_START: str = "plan:start"
PLAN_END: str = "plan:end"

# Provider
PROVIDER_REQUEST: str = "provider:request"
PROVIDER_RESPONSE: str = "provider:response"
PROVIDER_RETRY: str = "provider:retry"
PROVIDER_ERROR: str = "provider:error"
PROVIDER_THROTTLE: str = "provider:throttle"
PROVIDER_TOOL_SEQUENCE_REPAIRED: str = "provider:tool_sequence_repaired"
PROVIDER_RESOLVE: str = "provider:resolve"

# LLM
LLM_REQUEST: str = "llm:request"
LLM_RESPONSE: str = "llm:response"

# Content Blocks
CONTENT_BLOCK_START: str = "content_block:start"
CONTENT_BLOCK_DELTA: str = "content_block:delta"
CONTENT_BLOCK_END: str = "content_block:end"

# Thinking
THINKING_DELTA: str = "thinking:delta"
THINKING_FINAL: str = "thinking:final"

# Tools
TOOL_PRE: str = "tool:pre"
TOOL_POST: str = "tool:post"
TOOL_ERROR: str = "tool:error"

# Context
CONTEXT_PRE_COMPACT: str = "context:pre_compact"
CONTEXT_POST_COMPACT: str = "context:post_compact"
CONTEXT_COMPACTION: str = "context:compaction"
CONTEXT_INCLUDE: str = "context:include"

# Orchestrator
ORCHESTRATOR_COMPLETE: str = "orchestrator:complete"
EXECUTION_START: str = "execution:start"
EXECUTION_END: str = "execution:end"

# User
USER_NOTIFICATION: str = "user:notification"

# Artifacts
ARTIFACT_WRITE: str = "artifact:write"
ARTIFACT_READ: str = "artifact:read"

# Policy / Approvals
POLICY_VIOLATION: str = "policy:violation"
APPROVAL_REQUIRED: str = "approval:required"
APPROVAL_GRANTED: str = "approval:granted"
APPROVAL_DENIED: str = "approval:denied"

# Cancellation
CANCEL_REQUESTED: str = "cancel:requested"
CANCEL_COMPLETED: str = "cancel:completed"

# Delegate
DELEGATE_AGENT_SPAWNED: str = "delegate:agent_spawned"
DELEGATE_AGENT_COMPLETED: str = "delegate:agent_completed"
DELEGATE_AGENT_RESUMED: str = "delegate:agent_resumed"
DELEGATE_ERROR: str = "delegate:error"

__all__ = [
    # Session Lifecycle
    "SESSION_START",
    "SESSION_END",
    "SESSION_FORK",
    "SESSION_RESUME",
    # Prompt
    "PROMPT_SUBMIT",
    "PROMPT_COMPLETE",
    # Planning
    "PLAN_START",
    "PLAN_END",
    # Provider
    "PROVIDER_REQUEST",
    "PROVIDER_RESPONSE",
    "PROVIDER_RETRY",
    "PROVIDER_ERROR",
    "PROVIDER_THROTTLE",
    "PROVIDER_TOOL_SEQUENCE_REPAIRED",
    "PROVIDER_RESOLVE",
    # LLM
    "LLM_REQUEST",
    "LLM_RESPONSE",
    # Content Blocks
    "CONTENT_BLOCK_START",
    "CONTENT_BLOCK_DELTA",
    "CONTENT_BLOCK_END",
    # Thinking
    "THINKING_DELTA",
    "THINKING_FINAL",
    # Tools
    "TOOL_PRE",
    "TOOL_POST",
    "TOOL_ERROR",
    # Context
    "CONTEXT_PRE_COMPACT",
    "CONTEXT_POST_COMPACT",
    "CONTEXT_COMPACTION",
    "CONTEXT_INCLUDE",
    # Orchestrator
    "ORCHESTRATOR_COMPLETE",
    "EXECUTION_START",
    "EXECUTION_END",
    # User
    "USER_NOTIFICATION",
    # Artifacts
    "ARTIFACT_WRITE",
    "ARTIFACT_READ",
    # Policy / Approvals
    "POLICY_VIOLATION",
    "APPROVAL_REQUIRED",
    "APPROVAL_GRANTED",
    "APPROVAL_DENIED",
    # Cancellation
    "CANCEL_REQUESTED",
    "CANCEL_COMPLETED",
    # Delegate
    "DELEGATE_AGENT_SPAWNED",
    "DELEGATE_AGENT_COMPLETED",
    "DELEGATE_AGENT_RESUMED",
    "DELEGATE_ERROR",
]
