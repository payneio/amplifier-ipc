"""Tests for the JSON-RPC 2.0 framing module."""

from __future__ import annotations

import asyncio
import json
import pytest

from amplifier_ipc_protocol.framing import read_message, write_message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reader_from_bytes(data: bytes) -> asyncio.StreamReader:
    """Create an asyncio.StreamReader pre-loaded with the given bytes."""
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


class _WriteSink:
    """Collects bytes written via write()/drain() for assertions."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass  # no-op for testing

    @property
    def value(self) -> bytes:
        return bytes(self._buf)


# ---------------------------------------------------------------------------
# read_message tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_message_simple():
    """Read a single JSON-RPC message from a stream."""
    msg = {"jsonrpc": "2.0", "method": "ping", "id": 1}
    data = (json.dumps(msg) + "\n").encode()
    reader = _make_reader_from_bytes(data)
    result = await read_message(reader)
    assert result == msg


@pytest.mark.asyncio
async def test_read_message_eof_returns_none():
    """Empty stream (EOF) returns None."""
    reader = _make_reader_from_bytes(b"")
    result = await read_message(reader)
    assert result is None


@pytest.mark.asyncio
async def test_read_message_malformed_json_raises():
    """Non-JSON content raises ValueError matching 'Invalid JSON'."""
    data = b"this is not json\n"
    reader = _make_reader_from_bytes(data)
    with pytest.raises(ValueError, match="Invalid JSON"):
        await read_message(reader)


@pytest.mark.asyncio
async def test_read_message_multiple():
    """Read two messages sequentially; third call returns None (EOF)."""
    msg1 = {"jsonrpc": "2.0", "method": "a", "id": 1}
    msg2 = {"jsonrpc": "2.0", "method": "b", "id": 2}
    data = (json.dumps(msg1) + "\n" + json.dumps(msg2) + "\n").encode()
    reader = _make_reader_from_bytes(data)

    result1 = await read_message(reader)
    result2 = await read_message(reader)
    result3 = await read_message(reader)

    assert result1 == msg1
    assert result2 == msg2
    assert result3 is None


@pytest.mark.asyncio
async def test_read_message_skips_blank_lines():
    """Blank lines between messages are transparently skipped."""
    msg = {"jsonrpc": "2.0", "method": "hello", "id": 3}
    data = ("\n\n" + json.dumps(msg) + "\n").encode()
    reader = _make_reader_from_bytes(data)
    result = await read_message(reader)
    assert result == msg


# ---------------------------------------------------------------------------
# write_message tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_message_simple():
    """write_message writes a JSON line ending with newline."""
    msg = {"jsonrpc": "2.0", "method": "ping", "id": 1}
    sink = _WriteSink()
    await write_message(sink, msg)
    written = sink.value
    assert written.endswith(b"\n")
    assert json.loads(written.strip()) == msg


@pytest.mark.asyncio
async def test_write_message_no_extra_newlines():
    """write_message produces exactly one JSON line + trailing newline."""
    msg = {"jsonrpc": "2.0", "result": "ok", "id": 2}
    sink = _WriteSink()
    await write_message(sink, msg)
    # Split on newline: should give exactly ["<json>", ""]
    parts = sink.value.split(b"\n")
    assert len(parts) == 2
    assert parts[1] == b""  # trailing empty after final \n


@pytest.mark.asyncio
async def test_round_trip():
    """Write then read back; verify message equality is preserved."""
    msg = {"jsonrpc": "2.0", "method": "test", "params": {"key": "value"}, "id": 42}
    sink = _WriteSink()
    await write_message(sink, msg)

    reader = _make_reader_from_bytes(sink.value)
    result = await read_message(reader)
    assert result == msg


@pytest.mark.asyncio
async def test_read_message_large_payload_with_adequate_limit():
    """read_message succeeds when the reader limit is large enough for the payload.

    This verifies that a message larger than the default 64 KB StreamReader limit
    can be processed when a sufficiently large limit is used — as required by
    protocol messages that embed large system prompts.
    """
    large_payload = "x" * (128 * 1024)  # 128 KB string
    msg = {
        "jsonrpc": "2.0",
        "method": "orchestrator.execute",
        "params": {"prompt": large_payload},
        "id": 1,
    }

    sink = _WriteSink()
    await write_message(sink, msg)

    # Use a reader with a 10 MB limit — large enough to hold the payload.
    reader = asyncio.StreamReader(limit=10 * 1024 * 1024)
    reader.feed_data(sink.value)
    reader.feed_eof()

    result = await read_message(reader)
    assert result is not None
    assert result["id"] == 1
    assert result["params"]["prompt"] == large_payload


@pytest.mark.asyncio
async def test_read_message_large_payload_exceeds_default_limit():
    """read_message raises ValueError when payload exceeds the default 64 KB limit.

    This is the failure mode that necessitates using a larger StreamReader limit
    in the server and service lifecycle.
    """
    large_payload = "x" * (128 * 1024)  # 128 KB string
    msg = {
        "jsonrpc": "2.0",
        "method": "orchestrator.execute",
        "params": {"prompt": large_payload},
        "id": 1,
    }

    sink = _WriteSink()
    await write_message(sink, msg)

    # Default 64 KB limit — too small for a 128 KB payload.
    reader = asyncio.StreamReader()  # default limit = 65536 bytes
    reader.feed_data(sink.value)
    reader.feed_eof()

    with pytest.raises(ValueError):
        await read_message(reader)
