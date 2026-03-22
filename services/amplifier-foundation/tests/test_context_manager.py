"""Tests for SimpleContextManager — discovery, message storage, and clear."""

from __future__ import annotations

import pytest
from amplifier_ipc.protocol import Message
from amplifier_ipc.protocol.discovery import scan_package


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
