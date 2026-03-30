"""Tests for SimpleContextManager — discovery, message storage, and clear."""

from __future__ import annotations

import pytest
from amplifier_ipc.protocol import Message
from amplifier_ipc.protocol.discovery import scan_package


# ---------------------------------------------------------------------------
# MockClient helper for event emission tests
# ---------------------------------------------------------------------------


class MockClient:
    """Mock IPC client that records hook_emit calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []  # (method, data)

    async def request(self, method: str, data: dict) -> None:
        self.calls.append((method, data))


def _hook_emits(client: MockClient, event: str) -> list[dict]:
    """Return all data payloads emitted for a specific event name."""
    return [
        data
        for method, data in client.calls
        if method == "request.hook_emit" and data.get("event") == event
    ]


# ---------------------------------------------------------------------------
# Test 1: Discovery via scan_package
# ---------------------------------------------------------------------------


def test_context_manager_discovered() -> None:
    """'simple' context manager must be found in context_managers by scan_package."""
    components = scan_package("amplifier_foundation")
    assert "context_manager" in components, (
        "scan_package must return 'context_manager' key"
    )
    names = [cm.name for cm in components["context_manager"]]
    assert "simple" in names, f"'simple' not found in context_managers; found: {names}"


# ---------------------------------------------------------------------------
# Test 2: add_message and get_messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_and_get_messages() -> None:
    """add_message stores messages; get_messages returns them with correct roles."""
    from amplifier_foundation.context_managers.simple import SimpleContextManager  # type: ignore[import]

    cm = SimpleContextManager()

    user_msg = Message(role="user", content="Hello, world!")
    assistant_msg = Message(role="assistant", content="Hi there!")

    await cm.add_message(user_msg)
    await cm.add_message(assistant_msg)

    messages = await cm.get_messages(provider_info={})

    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"


# ---------------------------------------------------------------------------
# Test 3: clear() empties message list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_messages() -> None:
    """clear() must remove all stored messages."""
    from amplifier_foundation.context_managers.simple import SimpleContextManager  # type: ignore[import]

    cm = SimpleContextManager()

    await cm.add_message(Message(role="user", content="Some message"))
    await cm.add_message(Message(role="assistant", content="Some reply"))

    assert len(await cm.get_messages(provider_info={})) == 2

    await cm.clear()

    assert len(await cm.get_messages(provider_info={})) == 0


# ---------------------------------------------------------------------------
# Test 4: client attribute injection support
# ---------------------------------------------------------------------------


def test_context_manager_has_client_attribute() -> None:
    """SimpleContextManager must have a 'client' attribute that defaults to None and can be set."""
    from amplifier_foundation.context_managers.simple import SimpleContextManager  # type: ignore[import]

    cm = SimpleContextManager()

    # (1) attribute exists
    assert hasattr(cm, "client"), "SimpleContextManager must have a 'client' attribute"

    # (2) defaults to None
    assert cm.client is None, "client attribute must default to None"

    # (3) can be set
    mock_client = object()
    cm.client = mock_client
    assert cm.client is mock_client, "client attribute must be settable"


# ---------------------------------------------------------------------------
# Test 5: Compaction events emitted when compaction occurs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compaction_events_emitted_when_compaction_occurs() -> None:
    """All three compaction events must fire with correct payloads when compaction occurs."""
    from amplifier_foundation.context_managers.simple import SimpleContextManager  # type: ignore[import]
    from amplifier_ipc_protocol.events import (
        CONTEXT_COMPACTION,
        CONTEXT_POST_COMPACT,
        CONTEXT_PRE_COMPACT,
    )

    cm = SimpleContextManager()
    client = MockClient()
    cm.client = client

    # Configure tight budget so compaction triggers with 4 messages of 200 chars
    cm.max_tokens = 100
    cm.compact_threshold = 0.50
    cm.target_usage = 0.30
    cm.compaction_notice_enabled = False

    long_content = "x" * 200  # 200 chars ≈ 50 tokens each
    for i in range(4):
        role = "user" if i % 2 == 0 else "assistant"
        await cm.add_message(Message(role=role, content=long_content))

    await cm.get_messages(provider_info={})

    # Verify all 3 event types were emitted
    pre_emits = _hook_emits(client, CONTEXT_PRE_COMPACT)
    post_emits = _hook_emits(client, CONTEXT_POST_COMPACT)
    compaction_emits = _hook_emits(client, CONTEXT_COMPACTION)

    assert len(pre_emits) >= 1, "context:pre_compact must be emitted"
    assert len(post_emits) >= 1, "context:post_compact must be emitted"
    assert len(compaction_emits) >= 1, "context:compaction must be emitted"

    # Verify pre_compact payload
    pre_payload = pre_emits[0]["data"]
    assert "message_count" in pre_payload, "pre_compact must have message_count"
    assert "token_count" in pre_payload, "pre_compact must have token_count"
    assert isinstance(pre_payload["message_count"], int)
    assert isinstance(pre_payload["token_count"], int)

    # Verify post_compact payload
    post_payload = post_emits[0]["data"]
    assert "message_count" in post_payload, "post_compact must have message_count"
    assert "token_count" in post_payload, "post_compact must have token_count"
    assert isinstance(post_payload["message_count"], int)
    assert isinstance(post_payload["token_count"], int)
    # post-compaction message count should be <= pre-compaction message count
    assert post_payload["message_count"] <= pre_payload["message_count"]

    # Verify compaction event payload has all required stats fields
    compaction_payload = compaction_emits[0]["data"]
    for field in [
        "before_tokens",
        "after_tokens",
        "before_messages",
        "after_messages",
        "messages_removed",
        "messages_truncated",
        "user_messages_stubbed",
        "system_messages_preserved",
        "strategy_level",
        "budget",
        "target_tokens",
        "protected_recent",
        "protected_tool_results",
    ]:
        assert field in compaction_payload, f"compaction event must have '{field}'"


# ---------------------------------------------------------------------------
# Test 6: No compaction events when compaction is not needed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_compaction_events_when_not_needed() -> None:
    """No compaction events must fire when messages fit within the budget."""
    from amplifier_foundation.context_managers.simple import SimpleContextManager  # type: ignore[import]
    from amplifier_ipc_protocol.events import (
        CONTEXT_COMPACTION,
        CONTEXT_POST_COMPACT,
        CONTEXT_PRE_COMPACT,
    )

    cm = SimpleContextManager()
    client = MockClient()
    cm.client = client

    # Short messages that easily fit within default budget
    await cm.add_message(Message(role="user", content="Hello"))
    await cm.add_message(Message(role="assistant", content="Hi there!"))

    await cm.get_messages(provider_info={})

    # No events should be emitted
    assert _hook_emits(client, CONTEXT_PRE_COMPACT) == [], (
        "context:pre_compact must not fire when no compaction needed"
    )
    assert _hook_emits(client, CONTEXT_POST_COMPACT) == [], (
        "context:post_compact must not fire when no compaction needed"
    )
    assert _hook_emits(client, CONTEXT_COMPACTION) == [], (
        "context:compaction must not fire when no compaction needed"
    )


# ---------------------------------------------------------------------------
# Test 7: Compaction works without client (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compaction_works_without_client() -> None:
    """SimpleContextManager must not crash when client is None, even during compaction."""
    from amplifier_foundation.context_managers.simple import SimpleContextManager  # type: ignore[import]

    cm = SimpleContextManager()
    # client defaults to None — do NOT set it

    cm.max_tokens = 100
    cm.compact_threshold = 0.50
    cm.target_usage = 0.30
    cm.compaction_notice_enabled = False

    long_content = "x" * 200
    for i in range(4):
        role = "user" if i % 2 == 0 else "assistant"
        await cm.add_message(Message(role=role, content=long_content))

    # Should not raise even though client is None
    messages = await cm.get_messages(provider_info={})
    assert isinstance(messages, list)
