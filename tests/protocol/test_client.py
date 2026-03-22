"""Tests for the JSON-RPC 2.0 client module."""

from __future__ import annotations

import asyncio
import json

import pytest

from amplifier_ipc.protocol.client import Client
from amplifier_ipc.protocol.errors import JsonRpcError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockWriter:
    """Collects bytes written via write()/drain() for assertions."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass  # no-op for testing

    @property
    def messages(self) -> list[dict]:
        """Parse all written newline-delimited JSON messages."""
        result = []
        for line in self._buf.split(b"\n"):
            line = line.strip()
            if line:
                result.append(json.loads(line))
        return result


def _make_pipe() -> tuple[asyncio.StreamReader, _MockWriter]:
    """Create a (StreamReader, MockWriter) pair for testing."""
    reader = asyncio.StreamReader()
    writer = _MockWriter()
    return reader, writer


def _feed_response(reader: asyncio.StreamReader, message: dict) -> None:
    """Feed a JSON message into the reader (simulating server response)."""
    data = (json.dumps(message) + "\n").encode()
    reader.feed_data(data)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_notification():
    """Notification sent without id, has method and params."""
    reader, writer = _make_pipe()
    client = Client(reader, writer)

    await client.send_notification("notify/event", {"key": "value"})

    msgs = writer.messages
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg["method"] == "notify/event"
    assert msg["params"] == {"key": "value"}
    assert "id" not in msg
    assert msg.get("jsonrpc") == "2.0"


@pytest.mark.asyncio
async def test_request_sends_and_receives():
    """Sends a request and returns the result from the matched response."""
    reader, writer = _make_pipe()
    client = Client(reader, writer)

    # Schedule a response after the request is sent
    async def feed_after():
        await asyncio.sleep(0.01)
        # Figure out the id that was assigned
        _feed_response(reader, {"jsonrpc": "2.0", "id": 1, "result": "pong"})

    task = asyncio.create_task(feed_after())
    result = await client.request("ping")
    await task

    assert result == "pong"

    # Check the sent message
    msgs = writer.messages
    assert len(msgs) == 1
    req = msgs[0]
    assert req["jsonrpc"] == "2.0"
    assert req["method"] == "ping"
    assert req["id"] == 1
    assert "params" not in req or req["params"] is None


@pytest.mark.asyncio
async def test_request_auto_increments_id():
    """Two concurrent requests get unique, auto-incrementing ids."""
    reader, writer = _make_pipe()
    client = Client(reader, writer)

    async def feed_responses():
        await asyncio.sleep(0.01)
        _feed_response(reader, {"jsonrpc": "2.0", "id": 1, "result": "first"})
        _feed_response(reader, {"jsonrpc": "2.0", "id": 2, "result": "second"})

    feed_task = asyncio.create_task(feed_responses())

    # Start two concurrent requests
    r1_task = asyncio.create_task(client.request("method_a"))
    r2_task = asyncio.create_task(client.request("method_b"))

    r1, r2 = await asyncio.gather(r1_task, r2_task)
    await feed_task

    assert r1 == "first"
    assert r2 == "second"

    msgs = writer.messages
    assert len(msgs) == 2
    ids = {m["id"] for m in msgs}
    assert ids == {1, 2}


@pytest.mark.asyncio
async def test_request_raises_on_error_response():
    """Error response raises JsonRpcError with correct code and message."""
    reader, writer = _make_pipe()
    client = Client(reader, writer)

    async def feed_error():
        await asyncio.sleep(0.01)
        _feed_response(
            reader,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32601, "message": "Method not found"},
            },
        )

    task = asyncio.create_task(feed_error())

    with pytest.raises(JsonRpcError) as exc_info:
        await client.request("unknown_method")

    await task
    err = exc_info.value
    assert err.code == -32601
    assert err.message == "Method not found"


@pytest.mark.asyncio
async def test_request_handles_interleaved_notifications():
    """Notification between request and response doesn't break matching.

    The notification is received via the on_notification callback, while the
    request still resolves with its matched response.
    """
    reader, writer = _make_pipe()
    received_notifications: list[dict] = []

    def on_notification(msg: dict) -> None:
        received_notifications.append(msg)

    client = Client(reader, writer, on_notification=on_notification)

    async def feed_mixed():
        await asyncio.sleep(0.01)
        # Send a notification first, then the response
        _feed_response(
            reader,
            {"jsonrpc": "2.0", "method": "server/event", "params": {"data": 42}},
        )
        _feed_response(reader, {"jsonrpc": "2.0", "id": 1, "result": "ok"})

    task = asyncio.create_task(feed_mixed())
    result = await client.request("do_something")
    await task

    assert result == "ok"
    assert len(received_notifications) == 1
    notif = received_notifications[0]
    assert notif["method"] == "server/event"
    assert notif["params"] == {"data": 42}


@pytest.mark.asyncio
async def test_request_eof_raises():
    """EOF while waiting for a response raises ConnectionError."""
    reader, writer = _make_pipe()
    client = Client(reader, writer)

    async def send_eof():
        await asyncio.sleep(0.01)
        reader.feed_eof()

    task = asyncio.create_task(send_eof())

    with pytest.raises(ConnectionError):
        await client.request("wait_forever")

    await task
