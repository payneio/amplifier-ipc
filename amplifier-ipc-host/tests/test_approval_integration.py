"""Integration tests for the approval flow.

Validates the full approval event lifecycle from orchestrator notification
through to CLI response:
  1. approval_request notification → ApprovalRequestEvent yielded
  2. Consumer calls send_approval() → loop unblocks → CompleteEvent yielded
  3. send_approval() is immediately available (non-blocking, puts into queue)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from amplifier_ipc_host.config import HostSettings, SessionConfig
from amplifier_ipc_host.events import ApprovalRequestEvent, CompleteEvent
from amplifier_ipc_host.host import Host


async def test_approval_event_flows_to_consumer() -> None:
    """Approval request notification flows end-to-end: ApprovalRequestEvent then CompleteEvent.

    Patches write_message and read_message to simulate an orchestrator that:
    1. Sends an approval_request notification with tool_name, action, and risk_level.
    2. Then sends the final result response after approval is granted.

    Verifies:
    - Exactly 2 events are yielded: ApprovalRequestEvent followed by CompleteEvent.
    - The ApprovalRequestEvent carries the correct risk_level ('high') and
      tool_name ('bash') in its params dict.
    """
    config = SessionConfig(
        services=["orch"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()

    host = Host(config=config, settings=settings)

    fake_process = MagicMock()
    fake_process.stdin = MagicMock()
    fake_process.stdout = MagicMock()

    fake_service = MagicMock()
    fake_service.process = fake_process
    host._services = {"orch": fake_service}

    # Capture the execute_id so we can build a matching final response
    captured_id: list[str] = []

    async def fake_write(stream: object, message: dict) -> None:  # type: ignore[type-arg]
        if message.get("method") == "orchestrator.execute":
            captured_id.append(message["id"])

    read_call_count = 0

    async def fake_read(stream: object) -> dict | None:  # type: ignore[type-arg]
        nonlocal read_call_count
        read_call_count += 1
        if read_call_count == 1:
            # First read: approval_request notification
            return {
                "jsonrpc": "2.0",
                "method": "approval_request",
                "params": {
                    "tool_name": "bash",
                    "action": "rm -rf /tmp/test",
                    "risk_level": "high",
                },
            }
        else:
            # Second read: final result response matching the execute_id
            return {
                "jsonrpc": "2.0",
                "id": captured_id[0],
                "result": "done",
            }

    with (
        patch("amplifier_ipc_host.host.write_message", fake_write),
        patch("amplifier_ipc_host.host.read_message", fake_read),
    ):
        events = []
        async for event in host._orchestrator_loop(
            orchestrator_key="orch",
            prompt="run cleanup",
            system_prompt="be helpful",
        ):
            events.append(event)
            if isinstance(event, ApprovalRequestEvent):
                # Consumer unblocks the loop by granting approval
                host.send_approval(True)

    # Verify exactly 2 events: approval request then completion
    assert len(events) == 2
    assert isinstance(events[0], ApprovalRequestEvent)
    assert isinstance(events[1], CompleteEvent)

    # Verify the approval event carries the correct tool_name and risk_level
    approval_event = events[0]
    assert approval_event.params["tool_name"] == "bash"
    assert approval_event.params["risk_level"] == "high"
    assert approval_event.params["action"] == "rm -rf /tmp/test"


async def test_send_approval_available_immediately() -> None:
    """send_approval() puts decisions into the queue without blocking.

    Verifies that calling send_approval(True) then send_approval(False)
    immediately places both values into the internal _approval_queue,
    making them available for the orchestrator loop to consume.
    """
    config = SessionConfig(
        services=[],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()

    host = Host(config=config, settings=settings)

    # Both calls should succeed without blocking or raising
    host.send_approval(True)
    host.send_approval(False)

    # Both approval decisions should be immediately available in the queue
    assert host._approval_queue.qsize() == 2
