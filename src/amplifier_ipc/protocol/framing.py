"""JSON-RPC 2.0 newline-delimited framing transport.

Messages are single JSON objects, one per line, terminated by a newline.
"""

from __future__ import annotations

import asyncio
import json


async def read_message(reader: asyncio.StreamReader) -> dict | None:
    """Read one JSON-RPC message from an asyncio StreamReader.

    Skips blank lines. Returns parsed dict on success, None on EOF.
    Raises ValueError on malformed JSON.
    """
    while True:
        line_bytes = await reader.readline()
        if not line_bytes:
            return None
        line = line_bytes.decode().rstrip("\n")
        if not line.strip():
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc


async def write_message(writer: object, message: dict) -> None:
    """Serialize *message* to compact JSON and write it to *writer*.

    Uses compact separators (no extra spaces). Appends a newline, writes,
    then drains to flush the transport.
    """
    data = json.dumps(message, separators=(",", ":")) + "\n"
    writer.write(data.encode())  # type: ignore[attr-defined]
    await writer.drain()  # type: ignore[attr-defined]
