"""Tests for amplifier_ipc_protocol.events module.

Tests are written RED-first (before implementation exists).
"""


def test_events_module_importable() -> None:
    """The events module can be imported from amplifier_ipc_protocol."""
    from amplifier_ipc_protocol import events  # noqa: F401


def test_all_45_constants_defined() -> None:
    """events.py defines exactly 45 string constants."""
    from amplifier_ipc_protocol import events

    expected_constants = [
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
        # Policy/Approvals
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

    assert len(expected_constants) == 45, "Test itself has wrong count"

    for name in expected_constants:
        assert hasattr(events, name), f"Missing constant: {name}"

    # Count actual uppercase constants
    actual_constants = [
        name for name in dir(events) if name.isupper() and not name.startswith("_")
    ]
    assert len(actual_constants) == 45, (
        f"Expected exactly 45 constants, got {len(actual_constants)}: {actual_constants}"
    )


def test_canonical_string_values() -> None:
    """Each constant has the correct canonical string value."""
    from amplifier_ipc_protocol import events

    # Verified against amplifier_core smoke tests
    assert events.SESSION_START == "session:start"
    assert events.SESSION_END == "session:end"
    assert events.SESSION_FORK == "session:fork"
    assert events.SESSION_RESUME == "session:resume"
    assert events.PROMPT_SUBMIT == "prompt:submit"
    assert events.PROMPT_COMPLETE == "prompt:complete"
    assert events.PLAN_START == "plan:start"
    assert events.PLAN_END == "plan:end"
    assert events.PROVIDER_REQUEST == "provider:request"
    assert events.PROVIDER_RESPONSE == "provider:response"
    assert events.PROVIDER_RETRY == "provider:retry"
    assert events.PROVIDER_ERROR == "provider:error"
    assert events.PROVIDER_THROTTLE == "provider:throttle"
    assert events.PROVIDER_TOOL_SEQUENCE_REPAIRED == "provider:tool_sequence_repaired"
    assert events.PROVIDER_RESOLVE == "provider:resolve"
    assert events.LLM_REQUEST == "llm:request"
    assert events.LLM_RESPONSE == "llm:response"
    assert events.CONTENT_BLOCK_START == "content_block:start"
    assert events.CONTENT_BLOCK_DELTA == "content_block:delta"
    assert events.CONTENT_BLOCK_END == "content_block:end"
    assert events.THINKING_DELTA == "thinking:delta"
    assert events.THINKING_FINAL == "thinking:final"
    assert events.TOOL_PRE == "tool:pre"
    assert events.TOOL_POST == "tool:post"
    assert events.TOOL_ERROR == "tool:error"
    assert events.CONTEXT_PRE_COMPACT == "context:pre_compact"
    assert events.CONTEXT_POST_COMPACT == "context:post_compact"
    assert events.CONTEXT_COMPACTION == "context:compaction"
    assert events.CONTEXT_INCLUDE == "context:include"
    assert events.ORCHESTRATOR_COMPLETE == "orchestrator:complete"
    assert events.EXECUTION_START == "execution:start"
    assert events.EXECUTION_END == "execution:end"
    assert events.USER_NOTIFICATION == "user:notification"
    assert events.ARTIFACT_WRITE == "artifact:write"
    assert events.ARTIFACT_READ == "artifact:read"
    assert events.POLICY_VIOLATION == "policy:violation"
    assert events.APPROVAL_REQUIRED == "approval:required"
    assert events.APPROVAL_GRANTED == "approval:granted"
    assert events.APPROVAL_DENIED == "approval:denied"
    assert events.CANCEL_REQUESTED == "cancel:requested"
    assert events.CANCEL_COMPLETED == "cancel:completed"


def test_init_re_exports_all_constants() -> None:
    """__init__.py re-exports all 45 constants and lists them in __all__."""
    import amplifier_ipc_protocol

    assert hasattr(amplifier_ipc_protocol, "__all__"), "__init__.py must define __all__"
    assert len(amplifier_ipc_protocol.__all__) == 45, (
        f"Expected 45 items in __all__, got {len(amplifier_ipc_protocol.__all__)}"
    )

    # Spot-check re-exports
    assert hasattr(amplifier_ipc_protocol, "SESSION_START")
    assert amplifier_ipc_protocol.SESSION_START == "session:start"
    assert hasattr(amplifier_ipc_protocol, "CONTENT_BLOCK_START")
    assert amplifier_ipc_protocol.CONTENT_BLOCK_START == "content_block:start"


def test_direct_import_works() -> None:
    """Constants can be imported directly: from amplifier_ipc_protocol.events import ..."""
    from amplifier_ipc_protocol.events import SESSION_START, CONTENT_BLOCK_START

    assert SESSION_START == "session:start"
    assert CONTENT_BLOCK_START == "content_block:start"


def test_all_values_are_strings() -> None:
    """All exported constants are strings."""
    from amplifier_ipc_protocol import events

    for name in events.__all__:
        value = getattr(events, name)
        assert isinstance(value, str), f"{name} should be a string, got {type(value)}"


def test_all_values_use_colon_separator() -> None:
    """All event values follow the namespace:action convention."""
    from amplifier_ipc_protocol import events

    for name in events.__all__:
        value = getattr(events, name)
        assert ":" in value, f"{name} = {value!r} missing colon separator"
        namespace, _, action = value.partition(":")
        assert namespace, f"{name} has empty namespace"
        assert action, f"{name} has empty action"


def test_delegate_event_constants_defined_in_events_py() -> None:
    """events.py defines the 4 delegate:* event constants with correct string values."""
    from amplifier_ipc_protocol import events

    assert hasattr(events, "DELEGATE_AGENT_SPAWNED"), "Missing DELEGATE_AGENT_SPAWNED"
    assert hasattr(events, "DELEGATE_AGENT_COMPLETED"), (
        "Missing DELEGATE_AGENT_COMPLETED"
    )
    assert hasattr(events, "DELEGATE_AGENT_RESUMED"), "Missing DELEGATE_AGENT_RESUMED"
    assert hasattr(events, "DELEGATE_ERROR"), "Missing DELEGATE_ERROR"

    assert events.DELEGATE_AGENT_SPAWNED == "delegate:agent_spawned"
    assert events.DELEGATE_AGENT_COMPLETED == "delegate:agent_completed"
    assert events.DELEGATE_AGENT_RESUMED == "delegate:agent_resumed"
    assert events.DELEGATE_ERROR == "delegate:error"


def test_delegate_constants_in_events_all() -> None:
    """All 4 delegate:* constants are listed in events.__all__."""
    from amplifier_ipc_protocol import events

    assert "DELEGATE_AGENT_SPAWNED" in events.__all__
    assert "DELEGATE_AGENT_COMPLETED" in events.__all__
    assert "DELEGATE_AGENT_RESUMED" in events.__all__
    assert "DELEGATE_ERROR" in events.__all__


def test_delegate_constants_re_exported_from_init() -> None:
    """__init__.py re-exports all 4 delegate:* constants."""
    import amplifier_ipc_protocol

    assert hasattr(amplifier_ipc_protocol, "DELEGATE_AGENT_SPAWNED")
    assert hasattr(amplifier_ipc_protocol, "DELEGATE_AGENT_COMPLETED")
    assert hasattr(amplifier_ipc_protocol, "DELEGATE_AGENT_RESUMED")
    assert hasattr(amplifier_ipc_protocol, "DELEGATE_ERROR")

    assert amplifier_ipc_protocol.DELEGATE_AGENT_SPAWNED == "delegate:agent_spawned"
    assert amplifier_ipc_protocol.DELEGATE_AGENT_COMPLETED == "delegate:agent_completed"
    assert amplifier_ipc_protocol.DELEGATE_AGENT_RESUMED == "delegate:agent_resumed"
    assert amplifier_ipc_protocol.DELEGATE_ERROR == "delegate:error"


def test_delegate_constants_in_init_all() -> None:
    """All 4 delegate:* constants are in __init__.__all__."""
    import amplifier_ipc_protocol

    assert "DELEGATE_AGENT_SPAWNED" in amplifier_ipc_protocol.__all__
    assert "DELEGATE_AGENT_COMPLETED" in amplifier_ipc_protocol.__all__
    assert "DELEGATE_AGENT_RESUMED" in amplifier_ipc_protocol.__all__
    assert "DELEGATE_ERROR" in amplifier_ipc_protocol.__all__


def test_direct_import_delegate_constants() -> None:
    """Delegate constants can be imported directly from amplifier_ipc_protocol.events."""
    from amplifier_ipc_protocol.events import (
        DELEGATE_AGENT_COMPLETED,
        DELEGATE_AGENT_RESUMED,
        DELEGATE_AGENT_SPAWNED,
        DELEGATE_ERROR,
    )

    assert DELEGATE_AGENT_SPAWNED == "delegate:agent_spawned"
    assert DELEGATE_AGENT_COMPLETED == "delegate:agent_completed"
    assert DELEGATE_AGENT_RESUMED == "delegate:agent_resumed"
    assert DELEGATE_ERROR == "delegate:error"
