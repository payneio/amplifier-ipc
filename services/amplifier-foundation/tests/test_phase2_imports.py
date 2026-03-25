"""Tests for Phase 2 event constant imports in StreamingOrchestrator.

Verifies that all 12 constants (3 existing + 9 new Phase 2) are imported
from amplifier_ipc_protocol.events in streaming.py.
"""

from __future__ import annotations

import amplifier_foundation.orchestrators.streaming as streaming_module


def test_phase2_constants_all_imported():
    """All 12 event constants must be importable from the streaming module namespace."""
    expected_constants = [
        "CONTENT_BLOCK_DELTA",
        "CONTENT_BLOCK_END",
        "CONTENT_BLOCK_START",
        "EXECUTION_END",
        "EXECUTION_START",
        "LLM_REQUEST",
        "LLM_RESPONSE",
        "PROVIDER_RESOLVE",
        "PROVIDER_RESPONSE",
        "PROVIDER_THROTTLE",
        "THINKING_DELTA",
        "THINKING_FINAL",
    ]
    for name in expected_constants:
        assert hasattr(streaming_module, name), (
            f"Expected {name} to be importable from streaming module, but it was not found"
        )


def test_phase2_constants_from_ipc_protocol():
    """The new constants must come from amplifier_ipc_protocol.events (not local defs)."""
    import amplifier_ipc_protocol.events as events

    new_constants = [
        "CONTENT_BLOCK_DELTA",
        "EXECUTION_END",
        "EXECUTION_START",
        "LLM_REQUEST",
        "LLM_RESPONSE",
        "PROVIDER_RESOLVE",
        "PROVIDER_THROTTLE",
        "THINKING_DELTA",
        "THINKING_FINAL",
    ]
    for name in new_constants:
        streaming_val = getattr(streaming_module, name, None)
        protocol_val = getattr(events, name, None)
        assert streaming_val is not None, f"{name} not found in streaming module"
        assert streaming_val == protocol_val, (
            f"{name} in streaming module ({streaming_val!r}) does not match "
            f"amplifier_ipc_protocol.events value ({protocol_val!r})"
        )
