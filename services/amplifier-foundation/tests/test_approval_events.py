"""Tests for approval:required/granted/denied event emission from _ApprovalCore."""

from __future__ import annotations

from typing import Any

import pytest

from amplifier_foundation.hooks.approval.approval_hook import _ApprovalCore
from amplifier_foundation.hooks.approval_hook import ApprovalHook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockClient:
    """Records IPC request calls made by the hook."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, Any]] = []

    async def request(self, method: str, params: Any = None) -> Any:
        self.requests.append((method, params))
        return {}


def _hook_emits(client: MockClient, event: str) -> list[dict[str, Any]]:
    """Extract hook_emit payloads from a MockClient's recorded requests.

    Filters by event name and returns a list of ``data`` dicts.
    """
    return [
        params["data"]
        for method, params in client.requests
        if method == "request.hook_emit" and params.get("event") == event
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_required_emitted_for_high_risk_tool() -> None:
    """_ApprovalCore emits approval:required when tool needs approval."""
    from amplifier_ipc_protocol.events import APPROVAL_REQUIRED

    client = MockClient()
    core = _ApprovalCore(config={})
    core.client = client

    await core._handle_tool_pre(
        "tool:pre",
        {"tool_name": "bash", "tool_input": {"command": "rm -rf /tmp/test"}},
    )

    emits = _hook_emits(client, APPROVAL_REQUIRED)
    assert len(emits) == 1, f"Expected 1 approval:required event, got {len(emits)}"
    assert emits[0]["tool_name"] == "bash"
    assert emits[0]["risk_level"] == "high"
    assert "action" in emits[0]


@pytest.mark.asyncio
async def test_approval_granted_emitted_on_auto_approve() -> None:
    """_ApprovalCore emits approval:granted when auto-approved in IPC mode."""
    from amplifier_ipc_protocol.events import APPROVAL_GRANTED

    client = MockClient()
    core = _ApprovalCore(config={})
    core.client = client

    # "rm -rf /tmp/test" does not match any DEFAULT_RULES auto-approve pattern,
    # so it falls through to IPC mode auto-approve
    result = await core._handle_tool_pre(
        "tool:pre",
        {"tool_name": "bash", "tool_input": {"command": "rm -rf /tmp/test"}},
    )

    assert result.action.value == "CONTINUE"

    emits = _hook_emits(client, APPROVAL_GRANTED)
    assert len(emits) == 1, f"Expected 1 approval:granted event, got {len(emits)}"
    assert emits[0]["tool_name"] == "bash"
    assert "reason" in emits[0]


@pytest.mark.asyncio
async def test_approval_denied_emitted_on_auto_deny() -> None:
    """_ApprovalCore emits approval:denied when auto-deny rule matches."""
    from amplifier_ipc_protocol.events import APPROVAL_DENIED

    client = MockClient()
    core = _ApprovalCore(config={"rules": [{"tool": "bash", "action": "auto_deny"}]})
    core.client = client

    result = await core._handle_tool_pre(
        "tool:pre",
        {"tool_name": "bash", "tool_input": {"command": "rm -rf /tmp/test"}},
    )

    assert result.action.value == "DENY"

    emits = _hook_emits(client, APPROVAL_DENIED)
    assert len(emits) == 1, f"Expected 1 approval:denied event, got {len(emits)}"
    assert emits[0]["tool_name"] == "bash"
    assert "reason" in emits[0]


@pytest.mark.asyncio
async def test_no_approval_events_for_safe_tool() -> None:
    """No events emitted for 'read_file' tool (does not need approval)."""
    from amplifier_ipc_protocol.events import (
        APPROVAL_DENIED,
        APPROVAL_GRANTED,
        APPROVAL_REQUIRED,
    )

    client = MockClient()
    core = _ApprovalCore(config={})
    core.client = client

    await core._handle_tool_pre(
        "tool:pre",
        {"tool_name": "read_file", "tool_input": {"file_path": "/tmp/test.txt"}},
    )

    assert _hook_emits(client, APPROVAL_REQUIRED) == []
    assert _hook_emits(client, APPROVAL_GRANTED) == []
    assert _hook_emits(client, APPROVAL_DENIED) == []


@pytest.mark.asyncio
async def test_approval_works_without_client() -> None:
    """No crash when client is None; result is CONTINUE for bash."""
    core = _ApprovalCore(config={})
    # client is None by default — no injection

    result = await core._handle_tool_pre(
        "tool:pre",
        {"tool_name": "bash", "tool_input": {"command": "rm -rf /tmp/test"}},
    )

    assert result.action.value == "CONTINUE"


@pytest.mark.asyncio
async def test_approval_hook_proxy_passes_client() -> None:
    """ApprovalHook passes its client through to _ApprovalCore; approval:required is emitted."""
    from amplifier_ipc_protocol.events import APPROVAL_REQUIRED

    client = MockClient()
    hook = ApprovalHook()
    hook.client = client

    await hook.handle(
        "tool:pre",
        {"tool_name": "bash", "tool_input": {"command": "rm -rf /tmp/test"}},
    )

    emits = _hook_emits(client, APPROVAL_REQUIRED)
    assert len(emits) == 1, (
        f"Expected 1 approval:required event via proxy, got {len(emits)}"
    )
    assert emits[0]["tool_name"] == "bash"
