# Phase 1: IPC Protocol Library Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Build `amplifier-ipc-protocol`, the shared Python library that every IPC service and the host depends on — framing, errors, models, decorators, protocols, discovery, client, and server.

**Architecture:** A standalone Python package (`amplifier-ipc-protocol`) providing JSON-RPC 2.0 infrastructure over stdio. Services write components decorated with `@tool`, `@hook`, etc. The generic `Server` class discovers these at startup and handles the JSON-RPC read loop, method dispatch, `describe` responses, and content serving. The `Client` class sends JSON-RPC requests and matches responses by id. All wire data uses Pydantic v2 models that round-trip cleanly through JSON.

**Tech Stack:** Python 3.11+, Pydantic v2, hatchling build system, pytest + pytest-asyncio for tests. Zero other external dependencies.

**Design Document:** `amplifier-ipc/docs/plans/2026-03-20-amplifier-ipc-architecture-design.md`

**Project Root:** `/data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol/`

---

## Final File Structure

When all tasks are complete, the project will look like this:

```
amplifier-ipc/amplifier-ipc-protocol/
├── pyproject.toml
├── src/amplifier_ipc_protocol/
│   ├── __init__.py
│   ├── framing.py
│   ├── errors.py
│   ├── models.py
│   ├── decorators.py
│   ├── protocols.py
│   ├── discovery.py
│   ├── client.py
│   ├── server.py
│   └── content.py
└── tests/
    ├── conftest.py
    ├── test_framing.py
    ├── test_errors.py
    ├── test_models.py
    ├── test_decorators.py
    ├── test_protocols.py
    ├── test_discovery.py
    ├── test_client.py
    ├── test_server.py
    └── test_integration.py
```

---

## Reference: Existing Code to Port From

The new models are ported from these existing files in amplifier-lite. Read them before starting Task 4 (Models):

- **Models:** `amplifier-lite/amplifier-lite/src/amplifier_lite/models.py` — ToolResult, HookResult, Message, ChatRequest, ChatResponse, ToolCall, ToolSpec, HookAction, ContentBlock types, Usage
- **Protocols:** `amplifier-lite/amplifier-lite/src/amplifier_lite/protocols.py` — Tool, Provider, ContextManager, Orchestrator, Hook protocol definitions
- **Hooks:** `amplifier-lite/amplifier-lite/src/amplifier_lite/hooks.py` — HookRegistry, HookHandler, HookAction, HookResult chaining logic

---

## Conventions

- **Build system:** hatchling (matching amplifier-lite)
- **Test framework:** pytest with `pytest-asyncio`, `asyncio_mode = "auto"` in pyproject.toml
- **Models:** Pydantic v2 (`BaseModel`, `model_dump()`, `model_validate()`)
- **Protocols:** `typing.Protocol` (structural/duck typing, NOT ABC)
- **Test style:** Simple assertions, `@pytest.mark.asyncio` for async tests, section separators with `# ── SectionName ──...`
- **Run all tests:** `cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/ -v`
- **Run single test:** `cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_framing.py::test_name -v`

---

### Task 1: Project Scaffolding

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-protocol/pyproject.toml`
- Create: `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/__init__.py`
- Create: `amplifier-ipc/amplifier-ipc-protocol/tests/__init__.py`
- Create: `amplifier-ipc/amplifier-ipc-protocol/tests/conftest.py`

**Step 1: Create pyproject.toml**

Create `amplifier-ipc/amplifier-ipc-protocol/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "amplifier-ipc-protocol"
version = "0.1.0"
description = "Shared JSON-RPC 2.0 protocol library for amplifier IPC services"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[tool.hatch.build.targets.wheel]
packages = ["src/amplifier_ipc_protocol"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Step 2: Create the package __init__.py**

Create `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/__init__.py`:

```python
"""amplifier-ipc-protocol: Shared JSON-RPC 2.0 library for amplifier IPC services."""
```

**Step 3: Create empty test directory files**

Create `amplifier-ipc/amplifier-ipc-protocol/tests/__init__.py` as an empty file.

Create `amplifier-ipc/amplifier-ipc-protocol/tests/conftest.py`:

```python
"""Shared test utilities and fixtures for amplifier-ipc-protocol tests."""

from __future__ import annotations
```

**Step 4: Install the package in editable mode and verify**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && uv pip install -e ".[dev]"
```
Expected: Successful install with no errors.

**Step 5: Verify pytest runs with no tests**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/ -v
```
Expected: `no tests ran` with exit code 5 (no tests collected — that's fine).

**Step 6: Verify the package imports**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -c "import amplifier_ipc_protocol; print('OK')"
```
Expected: `OK`

**Step 7: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc && git init && git add amplifier-ipc-protocol/ && git commit -m "feat: scaffold amplifier-ipc-protocol package"
```

---

### Task 2: Framing

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/framing.py`
- Create: `amplifier-ipc/amplifier-ipc-protocol/tests/test_framing.py`

**Step 1: Write the tests**

Create `amplifier-ipc/amplifier-ipc-protocol/tests/test_framing.py`:

```python
"""Tests for amplifier_ipc_protocol.framing — newline-delimited JSON-RPC 2.0 framing."""

from __future__ import annotations

import asyncio
import json

import pytest

from amplifier_ipc_protocol.framing import read_message, write_message


# ── Helpers ──────────────────────────────────────────────────────────────


async def _make_reader_from_bytes(data: bytes) -> asyncio.StreamReader:
    """Create a StreamReader pre-loaded with the given bytes."""
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


class _WriteSink:
    """Collects bytes written via write() + drain()."""

    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.chunks.append(data)

    async def drain(self) -> None:
        pass

    def get_all(self) -> bytes:
        return b"".join(self.chunks)


# ── read_message ─────────────────────────────────────────────────────────


async def test_read_message_simple():
    """Read a single JSON-RPC message from a stream."""
    msg = {"jsonrpc": "2.0", "method": "describe", "id": 1}
    data = json.dumps(msg).encode() + b"\n"
    reader = await _make_reader_from_bytes(data)

    result = await read_message(reader)
    assert result == msg


async def test_read_message_eof_returns_none():
    """EOF on the stream returns None."""
    reader = await _make_reader_from_bytes(b"")

    result = await read_message(reader)
    assert result is None


async def test_read_message_malformed_json_raises():
    """Non-JSON line raises ValueError."""
    data = b"this is not json\n"
    reader = await _make_reader_from_bytes(data)

    with pytest.raises(ValueError, match="Invalid JSON"):
        await read_message(reader)


async def test_read_message_multiple():
    """Read multiple messages sequentially from one stream."""
    msg1 = {"jsonrpc": "2.0", "method": "describe", "id": 1}
    msg2 = {"jsonrpc": "2.0", "method": "tool.execute", "id": 2}
    data = json.dumps(msg1).encode() + b"\n" + json.dumps(msg2).encode() + b"\n"
    reader = await _make_reader_from_bytes(data)

    result1 = await read_message(reader)
    result2 = await read_message(reader)
    result3 = await read_message(reader)

    assert result1 == msg1
    assert result2 == msg2
    assert result3 is None  # EOF


async def test_read_message_skips_blank_lines():
    """Blank lines between messages are skipped."""
    msg = {"jsonrpc": "2.0", "method": "describe", "id": 1}
    data = b"\n\n" + json.dumps(msg).encode() + b"\n" + b"\n"
    reader = await _make_reader_from_bytes(data)

    result = await read_message(reader)
    assert result == msg


# ── write_message ────────────────────────────────────────────────────────


async def test_write_message_simple():
    """Write a JSON-RPC message as a newline-terminated JSON line."""
    msg = {"jsonrpc": "2.0", "method": "describe", "id": 1}
    sink = _WriteSink()

    await write_message(sink, msg)

    written = sink.get_all()
    assert written.endswith(b"\n")
    parsed = json.loads(written.strip())
    assert parsed == msg


async def test_write_message_no_extra_newlines():
    """Written output is exactly one JSON line followed by one newline."""
    msg = {"jsonrpc": "2.0", "result": {"ok": True}, "id": 1}
    sink = _WriteSink()

    await write_message(sink, msg)

    written = sink.get_all()
    lines = written.split(b"\n")
    # Should be exactly ["<json>", ""] (line + trailing newline)
    assert len(lines) == 2
    assert lines[1] == b""


# ── Round-trip ───────────────────────────────────────────────────────────


async def test_round_trip():
    """Write a message, then read it back — verify they match."""
    msg = {
        "jsonrpc": "2.0",
        "method": "tool.execute",
        "params": {"name": "bash", "input": {"command": "ls"}},
        "id": 42,
    }
    sink = _WriteSink()

    await write_message(sink, msg)

    reader = await _make_reader_from_bytes(sink.get_all())
    result = await read_message(reader)
    assert result == msg
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_framing.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_protocol.framing'`

**Step 3: Write the implementation**

Create `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/framing.py`:

```python
"""Newline-delimited JSON-RPC 2.0 framing over async streams.

Messages are single JSON objects, one per line, terminated by ``\\n``.
This is the lowest-level transport used by both Server and Client.
"""

from __future__ import annotations

import json
from typing import Any


async def read_message(reader: Any) -> dict[str, Any] | None:
    """Read one JSON-RPC message from an async stream reader.

    Args:
        reader: An ``asyncio.StreamReader`` (or anything with ``readline()``).

    Returns:
        Parsed JSON dict, or ``None`` on EOF.

    Raises:
        ValueError: If the line is not valid JSON.
    """
    while True:
        line = await reader.readline()
        if not line:
            return None
        stripped = line.strip()
        if not stripped:
            continue
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc


async def write_message(writer: Any, message: dict[str, Any]) -> None:
    """Write one JSON-RPC message to an async stream writer.

    Args:
        writer: An ``asyncio.StreamWriter`` (or anything with ``write()``
                and ``drain()``).
        message: The JSON-RPC message dict to send.
    """
    data = json.dumps(message, separators=(",", ":")).encode() + b"\n"
    writer.write(data)
    await writer.drain()
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_framing.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc && git add amplifier-ipc-protocol/src/amplifier_ipc_protocol/framing.py amplifier-ipc-protocol/tests/test_framing.py && git commit -m "feat: add JSON-RPC framing (read_message/write_message)"
```

---

### Task 3: Errors

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/errors.py`
- Create: `amplifier-ipc/amplifier-ipc-protocol/tests/test_errors.py`

**Step 1: Write the tests**

Create `amplifier-ipc/amplifier-ipc-protocol/tests/test_errors.py`:

```python
"""Tests for amplifier_ipc_protocol.errors — JSON-RPC 2.0 error codes and helpers."""

from __future__ import annotations

import pytest

from amplifier_ipc_protocol.errors import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JsonRpcError,
    make_error_response,
)


# ── Error code constants ─────────────────────────────────────────────────


def test_error_code_values():
    """JSON-RPC 2.0 error codes match the spec."""
    assert PARSE_ERROR == -32700
    assert INVALID_REQUEST == -32600
    assert METHOD_NOT_FOUND == -32601
    assert INVALID_PARAMS == -32602
    assert INTERNAL_ERROR == -32603


# ── make_error_response ──────────────────────────────────────────────────


def test_make_error_response_basic():
    """Produces a valid JSON-RPC 2.0 error response."""
    resp = make_error_response(1, PARSE_ERROR, "Parse error")

    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert resp["error"]["code"] == -32700
    assert resp["error"]["message"] == "Parse error"
    assert "data" not in resp["error"]


def test_make_error_response_with_data():
    """Error response includes optional data field."""
    resp = make_error_response(
        42, INTERNAL_ERROR, "Internal error", data={"traceback": "..."}
    )

    assert resp["id"] == 42
    assert resp["error"]["code"] == -32603
    assert resp["error"]["data"] == {"traceback": "..."}


def test_make_error_response_null_id():
    """Error response works with null id (for parse errors where id is unknown)."""
    resp = make_error_response(None, PARSE_ERROR, "Parse error")

    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] is None
    assert resp["error"]["code"] == -32700


# ── JsonRpcError ─────────────────────────────────────────────────────────


def test_json_rpc_error_is_exception():
    """JsonRpcError is a proper exception."""
    err = JsonRpcError(INTERNAL_ERROR, "something broke")

    assert isinstance(err, Exception)
    assert err.code == INTERNAL_ERROR
    assert err.message == "something broke"
    assert err.data is None
    assert str(err) == "something broke"


def test_json_rpc_error_with_data():
    """JsonRpcError carries optional data."""
    err = JsonRpcError(INVALID_PARAMS, "bad params", data={"field": "name"})

    assert err.code == INVALID_PARAMS
    assert err.data == {"field": "name"}


def test_json_rpc_error_to_response():
    """JsonRpcError.to_response() produces a valid error response dict."""
    err = JsonRpcError(METHOD_NOT_FOUND, "Method not found")
    resp = err.to_response(request_id=7)

    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 7
    assert resp["error"]["code"] == -32601
    assert resp["error"]["message"] == "Method not found"
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_errors.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_protocol.errors'`

**Step 3: Write the implementation**

Create `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/errors.py`:

```python
"""JSON-RPC 2.0 error codes and error response helpers."""

from __future__ import annotations

from typing import Any

# Standard JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def make_error_response(
    request_id: int | str | None,
    code: int,
    message: str,
    data: Any | None = None,
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 error response dict.

    Args:
        request_id: The ``id`` from the original request (or None).
        code: JSON-RPC error code.
        message: Human-readable error message.
        data: Optional additional error data.

    Returns:
        A dict ready to be serialized and sent as a JSON-RPC error response.
    """
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


class JsonRpcError(Exception):
    """Exception representing a JSON-RPC 2.0 error.

    Raised by the Client when a response contains an error, or by
    Server handlers to signal an error back to the caller.
    """

    def __init__(
        self,
        code: int,
        message: str,
        data: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_response(self, request_id: int | str | None) -> dict[str, Any]:
        """Convert this error to a JSON-RPC 2.0 error response dict."""
        return make_error_response(request_id, self.code, self.message, self.data)
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_errors.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc && git add amplifier-ipc-protocol/src/amplifier_ipc_protocol/errors.py amplifier-ipc-protocol/tests/test_errors.py && git commit -m "feat: add JSON-RPC 2.0 error codes and helpers"
```

---

### Task 4: Models

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/models.py`
- Create: `amplifier-ipc/amplifier-ipc-protocol/tests/test_models.py`

**Context:** Port the core data models from `amplifier-lite/amplifier-lite/src/amplifier_lite/models.py`. Read that file first. Keep the same field names and defaults, but focus on the models needed for the JSON-RPC wire protocol. Skip the LLM error hierarchy and approval models (those stay in amplifier-lite or get ported later). Skip the dataclass-based ContentBlock types — use only the Pydantic-based block types.

**Step 1: Write the tests**

Create `amplifier-ipc/amplifier-ipc-protocol/tests/test_models.py`:

```python
"""Tests for amplifier_ipc_protocol.models — Pydantic v2 wire-format models."""

from __future__ import annotations

import json

from amplifier_ipc_protocol.models import (
    ChatRequest,
    ChatResponse,
    HookAction,
    HookResult,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolCallBlock,
    ToolResult,
    ToolSpec,
    Usage,
)


# ── JSON round-trip helper ───────────────────────────────────────────────


def _round_trip(model_instance):
    """Serialize to JSON string and back, return new model instance."""
    model_cls = type(model_instance)
    json_str = json.dumps(model_instance.model_dump(mode="json"))
    return model_cls.model_validate(json.loads(json_str))


# ── ToolCall ─────────────────────────────────────────────────────────────


def test_tool_call_basic():
    tc = ToolCall(id="call_1", name="bash", arguments={"command": "ls"})
    assert tc.id == "call_1"
    assert tc.name == "bash"
    assert tc.arguments == {"command": "ls"}


def test_tool_call_accepts_tool_alias():
    """The 'tool' field name is accepted as an alias for 'name'."""
    tc = ToolCall.model_validate({"id": "call_1", "tool": "bash", "arguments": {}})
    assert tc.name == "bash"


def test_tool_call_json_round_trip():
    tc = ToolCall(id="call_1", name="bash", arguments={"command": "ls"})
    restored = _round_trip(tc)
    assert restored.id == tc.id
    assert restored.name == tc.name
    assert restored.arguments == tc.arguments


# ── Message ──────────────────────────────────────────────────────────────


def test_message_user():
    msg = Message(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"
    assert msg.tool_calls is None


def test_message_assistant_with_tool_calls():
    tc = ToolCall(id="call_1", name="search", arguments={"query": "python"})
    msg = Message(role="assistant", content=None, tool_calls=[tc])
    assert msg.tool_calls is not None
    assert len(msg.tool_calls) == 1


def test_message_tool_result():
    msg = Message(role="tool", content="result text", tool_call_id="call_1")
    assert msg.tool_call_id == "call_1"


def test_message_json_round_trip():
    msg = Message(role="user", content="hello", thinking_block={"text": "hmm"})
    restored = _round_trip(msg)
    assert restored.role == msg.role
    assert restored.content == msg.content
    assert restored.thinking_block == msg.thinking_block


def test_message_extra_fields_allowed():
    """Extra fields are preserved (extra='allow')."""
    msg = Message(role="user", content="hi", custom_field="extra")
    assert msg.custom_field == "extra"


# ── ToolSpec ─────────────────────────────────────────────────────────────


def test_tool_spec():
    spec = ToolSpec(
        name="bash",
        description="Run commands",
        parameters={"type": "object", "properties": {"command": {"type": "string"}}},
    )
    assert spec.name == "bash"
    assert "properties" in spec.parameters


def test_tool_spec_json_round_trip():
    spec = ToolSpec(name="bash", description="Run commands", parameters={"type": "object"})
    restored = _round_trip(spec)
    assert restored.name == spec.name


# ── ToolResult ───────────────────────────────────────────────────────────


def test_tool_result_success():
    result = ToolResult(success=True, output={"key": "value"})
    assert result.success is True
    assert result.output == {"key": "value"}
    assert result.error is None


def test_tool_result_error():
    result = ToolResult(success=False, error={"message": "boom"})
    assert result.success is False


def test_tool_result_get_serialized_output_dict():
    result = ToolResult(success=True, output={"stdout": "hello"})
    assert result.get_serialized_output() == '{"stdout": "hello"}'


def test_tool_result_get_serialized_output_string():
    result = ToolResult(success=True, output="plain text")
    assert result.get_serialized_output() == "plain text"


def test_tool_result_get_serialized_output_empty():
    result = ToolResult(success=True)
    assert result.get_serialized_output() == ""


def test_tool_result_json_round_trip():
    result = ToolResult(success=True, output={"data": [1, 2, 3]})
    restored = _round_trip(result)
    assert restored.success == result.success
    assert restored.output == result.output


# ── HookAction / HookResult ─────────────────────────────────────────────


def test_hook_action_values():
    assert HookAction.CONTINUE == "CONTINUE"
    assert HookAction.DENY == "DENY"
    assert HookAction.MODIFY == "MODIFY"
    assert HookAction.INJECT_CONTEXT == "INJECT_CONTEXT"
    assert HookAction.ASK_USER == "ASK_USER"


def test_hook_result_defaults():
    result = HookResult()
    assert result.action == HookAction.CONTINUE
    assert result.data is None
    assert result.reason is None
    assert result.ephemeral is False


def test_hook_result_deny():
    result = HookResult(action=HookAction.DENY, reason="Blocked")
    assert result.action == HookAction.DENY
    assert result.reason == "Blocked"


def test_hook_result_inject_context():
    msg = Message(role="user", content="injected")
    result = HookResult(action=HookAction.INJECT_CONTEXT, message=msg)
    assert result.message is not None
    assert result.message.content == "injected"


def test_hook_result_json_round_trip():
    result = HookResult(
        action=HookAction.MODIFY,
        data={"key": "val"},
        ephemeral=True,
        context_injection="extra context",
    )
    restored = _round_trip(result)
    assert restored.action == HookAction.MODIFY
    assert restored.data == {"key": "val"}
    assert restored.ephemeral is True
    assert restored.context_injection == "extra context"


# ── ChatRequest / ChatResponse ───────────────────────────────────────────


def test_chat_request():
    msg = Message(role="user", content="hi")
    spec = ToolSpec(name="calc", description="Calculator", parameters={})
    req = ChatRequest(messages=[msg], tools=[spec], system="Be helpful.")
    assert len(req.messages) == 1
    assert req.tools is not None
    assert req.system == "Be helpful."


def test_chat_request_minimal():
    msg = Message(role="user", content="hi")
    req = ChatRequest(messages=[msg])
    assert req.tools is None
    assert req.system is None


def test_chat_request_json_round_trip():
    msg = Message(role="user", content="hi")
    req = ChatRequest(messages=[msg], reasoning_effort="high")
    restored = _round_trip(req)
    assert len(restored.messages) == 1
    assert restored.reasoning_effort == "high"


def test_chat_response_text():
    resp = ChatResponse(content="Hello!", text="Hello!")
    assert resp.content == "Hello!"
    assert resp.text == "Hello!"


def test_chat_response_with_tool_calls():
    tc = ToolCall(id="call_1", name="search", arguments={"query": "test"})
    resp = ChatResponse(tool_calls=[tc])
    assert resp.tool_calls is not None
    assert len(resp.tool_calls) == 1


def test_chat_response_json_round_trip():
    usage = Usage(input_tokens=100, output_tokens=50, total_tokens=150)
    resp = ChatResponse(
        text="hi",
        usage=usage.model_dump(mode="json"),
        metadata={"model": "claude"},
    )
    restored = _round_trip(resp)
    assert restored.text == "hi"
    assert restored.metadata == {"model": "claude"}


# ── Content blocks ───────────────────────────────────────────────────────


def test_text_block():
    block = TextBlock(text="Hello")
    assert block.type == "text"
    assert block.text == "Hello"


def test_thinking_block():
    block = ThinkingBlock(thinking="Let me think...")
    assert block.type == "thinking"
    assert block.thinking == "Let me think..."


def test_tool_call_block():
    block = ToolCallBlock(id="call_1", name="bash", input={"command": "ls"})
    assert block.type == "tool_call"
    assert block.name == "bash"


# ── Usage ────────────────────────────────────────────────────────────────


def test_usage():
    usage = Usage(input_tokens=100, output_tokens=50, total_tokens=150)
    assert usage.input_tokens == 100
    assert usage.reasoning_tokens is None


def test_usage_json_round_trip():
    usage = Usage(
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        reasoning_tokens=20,
    )
    restored = _round_trip(usage)
    assert restored.input_tokens == 100
    assert restored.reasoning_tokens == 20
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_models.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_protocol.models'`

**Step 3: Write the implementation**

Create `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/models.py`:

```python
"""Pydantic v2 data models for the amplifier IPC wire protocol.

Ported from amplifier-lite's models.py with modifications for clean
JSON serialization across process boundaries.  Every model must
round-trip cleanly through ``model_dump(mode="json")`` → ``json.dumps``
→ ``json.loads`` → ``model_validate``.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


# ── Tool models ──────────────────────────────────────────────────────────


class ToolCall(BaseModel):
    """Tool call from an LLM response.

    Accepts ``"tool"`` as an alias for ``name`` because the orchestrator
    serialises tool calls as ``{"id": ..., "tool": ..., "arguments": ...}``.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    name: str = Field(
        default="",
        validation_alias=AliasChoices("name", "tool"),
        serialization_alias="tool",
    )
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolSpec(BaseModel):
    """Tool specification for ChatRequest tool lists."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Result of a tool execution."""

    model_config = ConfigDict(extra="allow")

    success: bool = True
    output: Any = None
    error: dict[str, Any] | None = None

    def get_serialized_output(self) -> str:
        """Serialize the result for inclusion in conversation context."""
        if self.output is not None:
            if isinstance(self.output, (dict, list)):
                return json.dumps(self.output)
            return str(self.output)
        return ""


# ── Message ──────────────────────────────────────────────────────────────


class Message(BaseModel):
    """Chat message with flexible content (str or list of content blocks)."""

    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    # Extended fields used by orchestrator / context manager
    metadata: dict[str, Any] | None = None
    thinking_block: dict[str, Any] | None = None


# ── Hook models ──────────────────────────────────────────────────────────


class HookAction(str, Enum):
    """Actions a hook handler can return."""

    CONTINUE = "CONTINUE"
    DENY = "DENY"
    MODIFY = "MODIFY"
    INJECT_CONTEXT = "INJECT_CONTEXT"
    ASK_USER = "ASK_USER"


class HookResult(BaseModel):
    """Result from a hook handler execution."""

    model_config = ConfigDict(extra="allow")

    action: HookAction = HookAction.CONTINUE
    data: dict[str, Any] | None = None
    reason: str | None = None
    message: Message | None = None
    question: str | None = None
    injected_messages: list[Message] = Field(default_factory=list)
    # Context injection fields
    ephemeral: bool = False
    context_injection: str | None = None
    context_injection_role: str = "user"
    append_to_last_tool_result: bool = False
    # Output control fields
    suppress_output: bool = False
    user_message: str | None = None
    user_message_level: str = "info"
    user_message_source: str | None = None
    # Approval gate fields
    approval_prompt: str | None = None
    approval_options: list[str] | None = None
    approval_timeout: float = 300.0
    approval_default: str = "deny"


# ── Chat request / response ─────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Request to an LLM provider."""

    model_config = ConfigDict(extra="allow")

    messages: list[Message]
    tools: list[ToolSpec] | None = None
    system: str | None = None
    reasoning_effort: str | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    response_format: Any | None = None


class ChatResponse(BaseModel):
    """Response from an LLM provider."""

    model_config = ConfigDict(extra="allow")

    content: str | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    text: str | None = None
    usage: Any | None = None
    content_blocks: list[Any] | None = None
    metadata: dict[str, Any] | None = None
    finish_reason: str | None = None


# ── Content block types (Pydantic-based) ─────────────────────────────────


class TextBlock(BaseModel):
    """Regular text content block."""

    model_config = ConfigDict(extra="allow")

    type: str = "text"
    text: str = ""
    visibility: str | None = None


class ThinkingBlock(BaseModel):
    """Model reasoning/thinking content block."""

    model_config = ConfigDict(extra="allow")

    type: str = "thinking"
    thinking: str = ""
    signature: str | None = None
    visibility: str | None = None
    content: list[Any] | None = None


class ToolCallBlock(BaseModel):
    """Tool call request content block."""

    model_config = ConfigDict(extra="allow")

    type: str = "tool_call"
    id: str = ""
    name: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    visibility: str | None = None


# ── Usage ────────────────────────────────────────────────────────────────


class Usage(BaseModel):
    """Token usage information from provider responses."""

    model_config = ConfigDict(extra="allow")

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_models.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc && git add amplifier-ipc-protocol/src/amplifier_ipc_protocol/models.py amplifier-ipc-protocol/tests/test_models.py && git commit -m "feat: add Pydantic v2 wire-format models"
```

---

### Task 5: Decorators

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/decorators.py`
- Create: `amplifier-ipc/amplifier-ipc-protocol/tests/test_decorators.py`

**Step 1: Write the tests**

Create `amplifier-ipc/amplifier-ipc-protocol/tests/test_decorators.py`:

```python
"""Tests for amplifier_ipc_protocol.decorators — component discovery markers."""

from __future__ import annotations

from amplifier_ipc_protocol.decorators import (
    context_manager,
    hook,
    orchestrator,
    provider,
    tool,
)


# ── @tool ────────────────────────────────────────────────────────────────


def test_tool_decorator_sets_metadata():
    @tool
    class MyTool:
        name = "my_tool"

    assert MyTool.__amplifier_component__ == "tool"


def test_tool_decorator_preserves_class():
    """Decorator returns the same class, not a wrapper."""

    @tool
    class MyTool:
        name = "my_tool"
        value = 42

    assert MyTool.value == 42
    instance = MyTool()
    assert instance.name == "my_tool"


# ── @hook ────────────────────────────────────────────────────────────────


def test_hook_decorator_sets_metadata():
    @hook(events=["tool:pre", "tool:post"], priority=10)
    class MyHook:
        name = "my_hook"

    assert MyHook.__amplifier_component__ == "hook"
    assert MyHook.__amplifier_hook_events__ == ["tool:pre", "tool:post"]
    assert MyHook.__amplifier_hook_priority__ == 10


def test_hook_decorator_default_priority():
    @hook(events=["prompt:submit"])
    class MyHook:
        name = "my_hook"

    assert MyHook.__amplifier_hook_priority__ == 0


def test_hook_decorator_preserves_class():
    @hook(events=["tool:pre"])
    class MyHook:
        name = "my_hook"
        value = 99

    assert MyHook.value == 99


# ── @orchestrator ────────────────────────────────────────────────────────


def test_orchestrator_decorator_sets_metadata():
    @orchestrator
    class MyOrchestrator:
        name = "streaming"

    assert MyOrchestrator.__amplifier_component__ == "orchestrator"


def test_orchestrator_decorator_preserves_class():
    @orchestrator
    class MyOrchestrator:
        name = "streaming"

    assert MyOrchestrator.name == "streaming"


# ── @context_manager ────────────────────────────────────────────────────


def test_context_manager_decorator_sets_metadata():
    @context_manager
    class MyContextManager:
        name = "simple"

    assert MyContextManager.__amplifier_component__ == "context_manager"


# ── @provider ────────────────────────────────────────────────────────────


def test_provider_decorator_sets_metadata():
    @provider
    class MyProvider:
        name = "anthropic"

    assert MyProvider.__amplifier_component__ == "provider"


# ── Edge cases ───────────────────────────────────────────────────────────


def test_decorated_class_is_same_object():
    """The decorator returns the exact same class object, not a copy."""

    class Original:
        name = "test"

    decorated = tool(Original)
    assert decorated is Original


def test_hook_decorated_class_is_same_object():
    class Original:
        name = "test"

    decorated = hook(events=["test"])(Original)
    assert decorated is Original
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_decorators.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_protocol.decorators'`

**Step 3: Write the implementation**

Create `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/decorators.py`:

```python
"""Component discovery decorators for amplifier IPC services.

These decorators mark classes as IPC components by attaching metadata
attributes.  They do NOT change class behavior — they only add
``__amplifier_component__`` (and hook-specific attributes) so the
generic Server can discover them at startup.

Usage::

    @tool
    class BashTool:
        name = "bash"
        ...

    @hook(events=["tool:pre"], priority=10)
    class ApprovalHook:
        name = "approval"
        ...

    @orchestrator
    class StreamingOrchestrator:
        name = "streaming"
        ...
"""

from __future__ import annotations

from typing import Any


def _mark_component(cls: type, component_type: str) -> type:
    """Attach component metadata to a class."""
    cls.__amplifier_component__ = component_type  # type: ignore[attr-defined]
    return cls


def tool(cls: type) -> type:
    """Mark a class as a Tool component."""
    return _mark_component(cls, "tool")


def hook(
    events: list[str],
    priority: int = 0,
) -> Any:
    """Mark a class as a Hook component.

    Args:
        events: List of event names this hook subscribes to.
        priority: Execution priority (lower = runs first).

    Returns:
        A decorator that marks the class.
    """

    def decorator(cls: type) -> type:
        _mark_component(cls, "hook")
        cls.__amplifier_hook_events__ = events  # type: ignore[attr-defined]
        cls.__amplifier_hook_priority__ = priority  # type: ignore[attr-defined]
        return cls

    return decorator


def orchestrator(cls: type) -> type:
    """Mark a class as an Orchestrator component."""
    return _mark_component(cls, "orchestrator")


def context_manager(cls: type) -> type:
    """Mark a class as a ContextManager component."""
    return _mark_component(cls, "context_manager")


def provider(cls: type) -> type:
    """Mark a class as a Provider component."""
    return _mark_component(cls, "provider")
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_decorators.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc && git add amplifier-ipc-protocol/src/amplifier_ipc_protocol/decorators.py amplifier-ipc-protocol/tests/test_decorators.py && git commit -m "feat: add component discovery decorators"
```

---

### Task 6: Protocols

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/protocols.py`
- Create: `amplifier-ipc/amplifier-ipc-protocol/tests/test_protocols.py`

**Context:** These are `typing.Protocol` classes (structural subtyping). They define what methods/attributes each component type must have. Read `amplifier-lite/amplifier-lite/src/amplifier_lite/protocols.py` for the existing patterns — the new versions update signatures for the IPC world (e.g., the Orchestrator receives a `Client` instead of direct object references).

**Step 1: Write the tests**

Create `amplifier-ipc/amplifier-ipc-protocol/tests/test_protocols.py`:

```python
"""Tests for amplifier_ipc_protocol.protocols — component interface contracts."""

from __future__ import annotations

from typing import Any, runtime_checkable

from amplifier_ipc_protocol.models import (
    ChatRequest,
    ChatResponse,
    HookResult,
    Message,
    ToolResult,
)
from amplifier_ipc_protocol.protocols import (
    ContextManagerProtocol,
    HookProtocol,
    OrchestratorProtocol,
    ProviderProtocol,
    ToolProtocol,
)


# ── ToolProtocol ─────────────────────────────────────────────────────────


def test_tool_protocol_satisfied():
    """A class with the right shape satisfies ToolProtocol."""

    class MyTool:
        name = "test"
        description = "A test tool"
        input_schema = {"type": "object"}

        async def execute(self, input: dict[str, Any]) -> ToolResult:
            return ToolResult(success=True, output="done")

    assert isinstance(MyTool(), ToolProtocol)


# ── HookProtocol ─────────────────────────────────────────────────────────


def test_hook_protocol_satisfied():
    class MyHook:
        name = "test"
        events = ["tool:pre"]
        priority = 0

        async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
            return HookResult()

    assert isinstance(MyHook(), HookProtocol)


# ── OrchestratorProtocol ─────────────────────────────────────────────────


def test_orchestrator_protocol_satisfied():
    class MyOrchestrator:
        name = "test"

        async def execute(self, prompt: str, config: dict[str, Any], client: Any) -> str:
            return "done"

    assert isinstance(MyOrchestrator(), OrchestratorProtocol)


# ── ContextManagerProtocol ───────────────────────────────────────────────


def test_context_manager_protocol_satisfied():
    class MyContextManager:
        name = "test"

        async def add_message(self, message: Message) -> None:
            pass

        async def get_messages(self, provider_info: dict[str, Any]) -> list[Message]:
            return []

        async def clear(self) -> None:
            pass

    assert isinstance(MyContextManager(), ContextManagerProtocol)


# ── ProviderProtocol ─────────────────────────────────────────────────────


def test_provider_protocol_satisfied():
    class MyProvider:
        name = "test"

        async def complete(self, request: ChatRequest) -> ChatResponse:
            return ChatResponse(text="hello")

    assert isinstance(MyProvider(), ProviderProtocol)


# ── All protocols are runtime_checkable ──────────────────────────────────


def test_all_protocols_are_runtime_checkable():
    """All protocols must be @runtime_checkable for isinstance() checks."""
    for proto in [
        ToolProtocol,
        HookProtocol,
        OrchestratorProtocol,
        ContextManagerProtocol,
        ProviderProtocol,
    ]:
        # runtime_checkable protocols have __protocol_attrs__
        assert hasattr(proto, "__protocol_attrs__") or hasattr(
            proto, "__callable_proto_members_only__"
        ), f"{proto.__name__} is not runtime_checkable"
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_protocols.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_protocol.protocols'`

**Step 3: Write the implementation**

Create `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/protocols.py`:

```python
"""Protocol definitions for amplifier IPC service components.

These are ``typing.Protocol`` classes that define the expected interface
for each component type.  Service authors implement these interfaces
and mark their classes with the corresponding decorator from
``amplifier_ipc_protocol.decorators``.

These protocols serve as documentation and enable static type checking.
They are all ``@runtime_checkable`` so you can use ``isinstance()``
checks in tests.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from amplifier_ipc_protocol.models import (
    ChatRequest,
    ChatResponse,
    HookResult,
    Message,
    ToolResult,
)


@runtime_checkable
class ToolProtocol(Protocol):
    """Contract for tool implementations.

    Attributes:
        name: Unique tool identifier.
        description: Human-readable tool description.
        input_schema: JSON Schema for tool parameters.
    """

    name: str
    description: str
    input_schema: dict[str, Any]

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute the tool with the given input dict."""
        ...


@runtime_checkable
class HookProtocol(Protocol):
    """Contract for lifecycle hook implementations.

    Attributes:
        name: Unique hook identifier.
        events: List of event names this hook subscribes to.
        priority: Execution priority (lower = runs first).
    """

    name: str
    events: list[str]
    priority: int

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle a lifecycle event and return a HookResult."""
        ...


@runtime_checkable
class OrchestratorProtocol(Protocol):
    """Contract for agent orchestration implementations.

    The orchestrator drives the agent loop. It receives a Client
    instance for making requests back to the host (tool calls,
    hook emits, provider completions, context operations).

    Attributes:
        name: Unique orchestrator identifier.
    """

    name: str

    async def execute(self, prompt: str, config: dict[str, Any], client: Any) -> str:
        """Execute the agent loop and return the final response."""
        ...


@runtime_checkable
class ContextManagerProtocol(Protocol):
    """Contract for conversation context management.

    Attributes:
        name: Unique context manager identifier.
    """

    name: str

    async def add_message(self, message: Message) -> None:
        """Append a message to the context."""
        ...

    async def get_messages(self, provider_info: dict[str, Any]) -> list[Message]:
        """Return messages formatted for the given provider."""
        ...

    async def clear(self) -> None:
        """Clear all messages from the context."""
        ...


@runtime_checkable
class ProviderProtocol(Protocol):
    """Contract for LLM provider implementations.

    Attributes:
        name: Unique provider identifier.
    """

    name: str

    async def complete(self, request: ChatRequest) -> ChatResponse:
        """Send a chat request and return the response."""
        ...
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_protocols.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc && git add amplifier-ipc-protocol/src/amplifier_ipc_protocol/protocols.py amplifier-ipc-protocol/tests/test_protocols.py && git commit -m "feat: add protocol definitions for component interfaces"
```

---

### Task 7: Discovery

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/discovery.py`
- Create: `amplifier-ipc/amplifier-ipc-protocol/tests/test_discovery.py`

**Context:** The discovery module scans a Python package's conventional directories to find decorated component classes and content files. It imports `.py` files, inspects classes for `__amplifier_component__`, and groups them by type. Content files are found by listing files in `agents/`, `context/`, `behaviors/`, `recipes/`, `sessions/` directories.

**Step 1: Write the tests**

Create `amplifier-ipc/amplifier-ipc-protocol/tests/test_discovery.py`:

```python
"""Tests for amplifier_ipc_protocol.discovery — component and content scanning."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from amplifier_ipc_protocol.discovery import scan_content, scan_package


# ── Helpers ──────────────────────────────────────────────────────────────


def _create_mock_package(tmp_path: Path, pkg_name: str, files: dict[str, str]) -> None:
    """Create a mock Python package with the given files.

    ``files`` maps relative paths (e.g., ``"tools/bash.py"``) to their content.
    An ``__init__.py`` is always created in the package root and any
    subdirectory that contains ``.py`` files.
    """
    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("")

    for rel_path, content in files.items():
        target = pkg_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        # Create __init__.py in any directory that has .py files
        if target.suffix == ".py":
            init = target.parent / "__init__.py"
            if not init.exists():
                init.write_text("")
        target.write_text(textwrap.dedent(content))


# ── scan_package ─────────────────────────────────────────────────────────


def test_scan_package_finds_tools(tmp_path: Path):
    _create_mock_package(
        tmp_path,
        "mock_service",
        {
            "tools/adder.py": """\
                from amplifier_ipc_protocol.decorators import tool

                @tool
                class AdderTool:
                    name = "adder"
                    description = "Adds two numbers"
                    input_schema = {"type": "object"}

                    async def execute(self, input):
                        return None
            """,
        },
    )
    sys.path.insert(0, str(tmp_path))
    try:
        result = scan_package("mock_service")
        assert "tool" in result
        assert len(result["tool"]) == 1
        assert result["tool"][0].name == "adder"
    finally:
        sys.path.remove(str(tmp_path))
        # Clean up imported modules
        for key in list(sys.modules):
            if key.startswith("mock_service"):
                del sys.modules[key]


def test_scan_package_finds_hooks(tmp_path: Path):
    _create_mock_package(
        tmp_path,
        "mock_hooks_service",
        {
            "hooks/approval.py": """\
                from amplifier_ipc_protocol.decorators import hook

                @hook(events=["tool:pre"], priority=10)
                class ApprovalHook:
                    name = "approval"
                    events = ["tool:pre"]
                    priority = 10

                    async def handle(self, event, data):
                        return None
            """,
        },
    )
    sys.path.insert(0, str(tmp_path))
    try:
        result = scan_package("mock_hooks_service")
        assert "hook" in result
        assert len(result["hook"]) == 1
        assert result["hook"][0].name == "approval"
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("mock_hooks_service"):
                del sys.modules[key]


def test_scan_package_finds_multiple_types(tmp_path: Path):
    _create_mock_package(
        tmp_path,
        "mock_multi_service",
        {
            "tools/my_tool.py": """\
                from amplifier_ipc_protocol.decorators import tool

                @tool
                class MyTool:
                    name = "my_tool"
                    description = "test"
                    input_schema = {}
                    async def execute(self, input): pass
            """,
            "orchestrators/my_orch.py": """\
                from amplifier_ipc_protocol.decorators import orchestrator

                @orchestrator
                class MyOrchestrator:
                    name = "my_orch"
                    async def execute(self, prompt, config, client): return ""
            """,
        },
    )
    sys.path.insert(0, str(tmp_path))
    try:
        result = scan_package("mock_multi_service")
        assert len(result.get("tool", [])) == 1
        assert len(result.get("orchestrator", [])) == 1
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("mock_multi_service"):
                del sys.modules[key]


def test_scan_package_empty_package(tmp_path: Path):
    """Package with no decorated classes returns empty groups."""
    _create_mock_package(tmp_path, "mock_empty_service", {})
    sys.path.insert(0, str(tmp_path))
    try:
        result = scan_package("mock_empty_service")
        # Should return a dict with empty lists or no keys
        total = sum(len(v) for v in result.values())
        assert total == 0
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("mock_empty_service"):
                del sys.modules[key]


# ── scan_content ─────────────────────────────────────────────────────────


def test_scan_content_finds_files(tmp_path: Path):
    _create_mock_package(
        tmp_path,
        "mock_content_service",
        {
            "agents/explorer.md": "# Explorer Agent",
            "context/rules.md": "# Rules",
            "behaviors/default.yaml": "name: default",
        },
    )
    sys.path.insert(0, str(tmp_path))
    try:
        paths = scan_content("mock_content_service")
        # Should find the content files
        path_strs = [str(p) for p in paths]
        assert any("explorer.md" in p for p in path_strs)
        assert any("rules.md" in p for p in path_strs)
        assert any("default.yaml" in p for p in path_strs)
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("mock_content_service"):
                del sys.modules[key]


def test_scan_content_empty_package(tmp_path: Path):
    """Package with no content directories returns empty list."""
    _create_mock_package(tmp_path, "mock_no_content", {})
    sys.path.insert(0, str(tmp_path))
    try:
        paths = scan_content("mock_no_content")
        assert paths == []
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("mock_no_content"):
                del sys.modules[key]
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_discovery.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_protocol.discovery'`

**Step 3: Write the implementation**

Create `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/discovery.py`:

```python
"""Component and content discovery for amplifier IPC services.

Scans a Python package's conventional directories to find:

- **Components**: Classes decorated with ``@tool``, ``@hook``,
  ``@orchestrator``, ``@context_manager``, or ``@provider``.
- **Content**: Files in ``agents/``, ``context/``, ``behaviors/``,
  ``recipes/``, ``sessions/`` directories.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Directories to scan for component classes
COMPONENT_DIRS = [
    "tools",
    "hooks",
    "orchestrators",
    "context_managers",
    "providers",
]

# Directories to scan for content files
CONTENT_DIRS = [
    "agents",
    "context",
    "behaviors",
    "recipes",
    "sessions",
]


def _get_package_dir(package_name: str) -> Path:
    """Get the filesystem path of an importable package."""
    mod = importlib.import_module(package_name)
    if mod.__file__ is None:
        raise ImportError(f"Cannot locate package {package_name}")
    return Path(mod.__file__).parent


def scan_package(package_name: str) -> dict[str, list[Any]]:
    """Scan a package for decorated component classes.

    Imports ``.py`` modules in conventional subdirectories (tools/,
    hooks/, orchestrators/, context_managers/, providers/) and collects
    classes that have the ``__amplifier_component__`` attribute.

    Args:
        package_name: Importable package name (e.g., ``"amplifier_foundation"``).

    Returns:
        Dict mapping component type strings to lists of **instances**
        of the discovered classes (each class is instantiated with no
        arguments).
    """
    pkg_dir = _get_package_dir(package_name)
    components: dict[str, list[Any]] = {}

    for subdir_name in COMPONENT_DIRS:
        subdir = pkg_dir / subdir_name
        if not subdir.is_dir():
            continue

        for py_file in sorted(subdir.rglob("*.py")):
            if py_file.name == "__init__.py":
                continue

            # Build the module path relative to the package
            rel = py_file.relative_to(pkg_dir)
            parts = list(rel.with_suffix("").parts)
            module_name = f"{package_name}.{'.'.join(parts)}"

            try:
                mod = importlib.import_module(module_name)
            except Exception:
                logger.warning("Failed to import %s", module_name, exc_info=True)
                continue

            for _attr_name, obj in inspect.getmembers(mod, inspect.isclass):
                component_type = getattr(obj, "__amplifier_component__", None)
                if component_type is None:
                    continue
                # Only include classes defined in this module (not imports)
                if obj.__module__ != mod.__name__:
                    continue

                if component_type not in components:
                    components[component_type] = []

                try:
                    instance = obj()
                    components[component_type].append(instance)
                except Exception:
                    logger.warning(
                        "Failed to instantiate %s.%s",
                        module_name,
                        obj.__name__,
                        exc_info=True,
                    )

    return components


def scan_content(package_name: str) -> list[str]:
    """Scan a package for content files.

    Looks in conventional content directories (agents/, context/,
    behaviors/, recipes/, sessions/) and returns relative paths
    from the package root.

    Args:
        package_name: Importable package name.

    Returns:
        List of relative path strings (e.g., ``"agents/explorer.md"``).
    """
    pkg_dir = _get_package_dir(package_name)
    paths: list[str] = []

    for subdir_name in CONTENT_DIRS:
        subdir = pkg_dir / subdir_name
        if not subdir.is_dir():
            continue

        for path in sorted(subdir.rglob("*")):
            if path.is_file() and path.name != "__init__.py":
                rel = path.relative_to(pkg_dir)
                paths.append(str(rel))

    return paths
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_discovery.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc && git add amplifier-ipc-protocol/src/amplifier_ipc_protocol/discovery.py amplifier-ipc-protocol/tests/test_discovery.py && git commit -m "feat: add component and content discovery"
```

---

### Task 8: Client

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/client.py`
- Create: `amplifier-ipc/amplifier-ipc-protocol/tests/test_client.py`

**Context:** The Client wraps an asyncio StreamReader/StreamWriter pair. It sends JSON-RPC requests with auto-incrementing ids, waits for matching responses, and handles interleaved notifications. This is critical because the host may send notifications while the client is waiting for a response.

**Step 1: Write the tests**

Create `amplifier-ipc/amplifier-ipc-protocol/tests/test_client.py`:

```python
"""Tests for amplifier_ipc_protocol.client — JSON-RPC 2.0 client."""

from __future__ import annotations

import asyncio
import json

import pytest

from amplifier_ipc_protocol.client import Client
from amplifier_ipc_protocol.errors import INTERNAL_ERROR, JsonRpcError


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_pipe() -> tuple[asyncio.StreamReader, "_MockWriter"]:
    """Create a connected reader + mock writer for testing."""
    reader = asyncio.StreamReader()
    writer = _MockWriter()
    return reader, writer


class _MockWriter:
    """Captures bytes written and provides drain()."""

    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.chunks.append(data)

    async def drain(self) -> None:
        pass

    def get_messages(self) -> list[dict]:
        """Parse all written JSON-RPC messages."""
        msgs = []
        for chunk in self.chunks:
            for line in chunk.split(b"\n"):
                line = line.strip()
                if line:
                    msgs.append(json.loads(line))
        return msgs


def _feed_response(reader: asyncio.StreamReader, response: dict) -> None:
    """Feed a JSON-RPC response into the reader."""
    data = json.dumps(response).encode() + b"\n"
    reader.feed_data(data)


# ── send_notification ────────────────────────────────────────────────────


async def test_send_notification():
    """Notifications are sent without an id."""
    reader, writer = _make_pipe()
    client = Client(reader, writer)

    await client.send_notification("stream.token", {"text": "hello"})

    msgs = writer.get_messages()
    assert len(msgs) == 1
    assert msgs[0]["jsonrpc"] == "2.0"
    assert msgs[0]["method"] == "stream.token"
    assert msgs[0]["params"] == {"text": "hello"}
    assert "id" not in msgs[0]


# ── request ──────────────────────────────────────────────────────────────


async def test_request_sends_and_receives():
    """request() sends a JSON-RPC request and returns the result."""
    reader, writer = _make_pipe()
    client = Client(reader, writer)

    # Start the request (it will wait for a response)
    task = asyncio.create_task(client.request("describe", {}))

    # Give the event loop a chance to send the request
    await asyncio.sleep(0.01)

    # Check what was sent
    msgs = writer.get_messages()
    assert len(msgs) == 1
    assert msgs[0]["method"] == "describe"
    request_id = msgs[0]["id"]

    # Feed the response
    _feed_response(reader, {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"name": "test-service"},
    })

    result = await asyncio.wait_for(task, timeout=2.0)
    assert result == {"name": "test-service"}


async def test_request_auto_increments_id():
    """Each request gets a unique incrementing id."""
    reader, writer = _make_pipe()
    client = Client(reader, writer)

    # Send two requests concurrently
    task1 = asyncio.create_task(client.request("method1", {}))
    task2 = asyncio.create_task(client.request("method2", {}))

    await asyncio.sleep(0.01)

    msgs = writer.get_messages()
    assert len(msgs) == 2
    ids = {m["id"] for m in msgs}
    assert len(ids) == 2  # IDs are unique

    # Respond to both
    for msg in msgs:
        _feed_response(reader, {
            "jsonrpc": "2.0",
            "id": msg["id"],
            "result": {"ok": True},
        })

    r1 = await asyncio.wait_for(task1, timeout=2.0)
    r2 = await asyncio.wait_for(task2, timeout=2.0)
    assert r1 == {"ok": True}
    assert r2 == {"ok": True}


async def test_request_raises_on_error_response():
    """Error responses raise JsonRpcError."""
    reader, writer = _make_pipe()
    client = Client(reader, writer)

    task = asyncio.create_task(client.request("bad_method", {}))
    await asyncio.sleep(0.01)

    msgs = writer.get_messages()
    request_id = msgs[0]["id"]

    _feed_response(reader, {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": INTERNAL_ERROR, "message": "Something broke"},
    })

    with pytest.raises(JsonRpcError) as exc_info:
        await asyncio.wait_for(task, timeout=2.0)

    assert exc_info.value.code == INTERNAL_ERROR
    assert exc_info.value.message == "Something broke"


async def test_request_handles_interleaved_notifications():
    """Notifications arriving between request and response don't break matching."""
    reader, writer = _make_pipe()
    client = Client(reader, writer)
    received_notifications: list[dict] = []
    client.on_notification = lambda method, params: received_notifications.append(
        {"method": method, "params": params}
    )

    task = asyncio.create_task(client.request("describe", {}))
    await asyncio.sleep(0.01)

    msgs = writer.get_messages()
    request_id = msgs[0]["id"]

    # Feed a notification BEFORE the response
    _feed_response(reader, {
        "jsonrpc": "2.0",
        "method": "stream.token",
        "params": {"text": "hello"},
    })
    # Then feed the actual response
    _feed_response(reader, {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"ok": True},
    })

    result = await asyncio.wait_for(task, timeout=2.0)
    assert result == {"ok": True}
    assert len(received_notifications) == 1
    assert received_notifications[0]["method"] == "stream.token"


async def test_request_eof_raises():
    """EOF while waiting for a response raises an error."""
    reader, writer = _make_pipe()
    client = Client(reader, writer)

    task = asyncio.create_task(client.request("describe", {}))
    await asyncio.sleep(0.01)

    reader.feed_eof()

    with pytest.raises(ConnectionError):
        await asyncio.wait_for(task, timeout=2.0)
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_client.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_protocol.client'`

**Step 3: Write the implementation**

Create `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/client.py`:

```python
"""JSON-RPC 2.0 client for amplifier IPC.

The Client wraps an asyncio StreamReader/StreamWriter pair and provides:

- ``request(method, params)`` — send a request, wait for the matching response
- ``send_notification(method, params)`` — fire-and-forget notification

The client handles interleaved notifications while waiting for a response
(critical for the orchestrator use case where the host may send
notifications between request and response).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from amplifier_ipc_protocol.errors import JsonRpcError
from amplifier_ipc_protocol.framing import read_message, write_message

logger = logging.getLogger(__name__)


class Client:
    """JSON-RPC 2.0 client over async stdio streams.

    Args:
        reader: An ``asyncio.StreamReader`` to read responses from.
        writer: An ``asyncio.StreamWriter`` (or compatible) to write requests to.
    """

    def __init__(self, reader: Any, writer: Any) -> None:
        self._reader = reader
        self._writer = writer
        self._next_id = 1
        self._pending: dict[int | str, asyncio.Future[Any]] = {}
        self._read_task: asyncio.Task[None] | None = None
        self.on_notification: Callable[[str, dict[str, Any]], Any] | None = None

    def _ensure_read_loop(self) -> None:
        """Start the background read loop if not already running."""
        if self._read_task is None or self._read_task.done():
            self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Background loop that reads messages and dispatches them."""
        try:
            while True:
                msg = await read_message(self._reader)
                if msg is None:
                    # EOF — fail all pending requests
                    for fut in self._pending.values():
                        if not fut.done():
                            fut.set_exception(
                                ConnectionError("Connection closed (EOF)")
                            )
                    self._pending.clear()
                    return

                # Is this a response (has "id" and either "result" or "error")?
                msg_id = msg.get("id")
                if msg_id is not None and ("result" in msg or "error" in msg):
                    fut = self._pending.pop(msg_id, None)
                    if fut is not None and not fut.done():
                        if "error" in msg:
                            err = msg["error"]
                            fut.set_exception(
                                JsonRpcError(
                                    err.get("code", -1),
                                    err.get("message", "Unknown error"),
                                    err.get("data"),
                                )
                            )
                        else:
                            fut.set_result(msg.get("result"))
                    continue

                # It's a notification (has "method" but no "id")
                if "method" in msg and self.on_notification is not None:
                    try:
                        self.on_notification(
                            msg["method"], msg.get("params", {})
                        )
                    except Exception:
                        logger.warning(
                            "Error in notification handler", exc_info=True
                        )
        except Exception:
            # Read loop crashed — fail all pending
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(
                        ConnectionError("Read loop crashed")
                    )
            self._pending.clear()

    async def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Send a JSON-RPC request and wait for the response.

        Args:
            method: The JSON-RPC method name.
            params: Optional parameters dict.

        Returns:
            The ``result`` field from the response.

        Raises:
            JsonRpcError: If the response contains an error.
            ConnectionError: If the connection is lost while waiting.
        """
        self._ensure_read_loop()

        request_id = self._next_id
        self._next_id += 1

        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "id": request_id,
        }
        if params is not None:
            message["params"] = params

        fut: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut

        await write_message(self._writer, message)

        return await fut

    async def send_notification(
        self, method: str, params: dict[str, Any] | None = None
    ) -> None:
        """Send a JSON-RPC notification (no response expected).

        Args:
            method: The JSON-RPC method name.
            params: Optional parameters dict.
        """
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            message["params"] = params

        await write_message(self._writer, message)
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_client.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc && git add amplifier-ipc-protocol/src/amplifier_ipc_protocol/client.py amplifier-ipc-protocol/tests/test_client.py && git commit -m "feat: add JSON-RPC 2.0 client with request/response matching"
```

---

### Task 9: Server and Content

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/content.py`
- Create: `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/server.py`
- Create: `amplifier-ipc/amplifier-ipc-protocol/tests/test_server.py`

**Context:** The Server is the generic JSON-RPC server base class. It reads stdin line-by-line, dispatches to handler methods, auto-generates `describe` responses from discovered components, and serves content files. The `content.py` module handles reading content files from a package's data directories. Every service runs this same server — it discovers components via decorators and handles everything generically.

**Step 1: Write the tests**

Create `amplifier-ipc/amplifier-ipc-protocol/tests/test_server.py`:

```python
"""Tests for amplifier_ipc_protocol.server — generic JSON-RPC 2.0 server."""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from amplifier_ipc_protocol.server import Server


# ── Helpers ──────────────────────────────────────────────────────────────


def _create_mock_package(tmp_path: Path, pkg_name: str, files: dict[str, str]) -> None:
    """Create a mock Python package with given files."""
    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("")

    for rel_path, content in files.items():
        target = pkg_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix == ".py":
            init = target.parent / "__init__.py"
            if not init.exists():
                init.write_text("")
        target.write_text(textwrap.dedent(content))


async def _send_and_collect(
    server: Server,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Feed messages to a server and collect all responses.

    Creates in-memory reader/writer, feeds all messages, then
    runs the server's message loop until EOF.
    """
    reader = asyncio.StreamReader()
    for msg in messages:
        reader.feed_data(json.dumps(msg).encode() + b"\n")
    reader.feed_eof()

    responses: list[dict[str, Any]] = []

    class MockWriter:
        def write(self, data: bytes) -> None:
            for line in data.split(b"\n"):
                line = line.strip()
                if line:
                    responses.append(json.loads(line))

        async def drain(self) -> None:
            pass

    writer = MockWriter()
    await server.handle_stream(reader, writer)
    return responses


# ── describe ─────────────────────────────────────────────────────────────


async def test_describe_empty_package(tmp_path: Path):
    """describe on an empty package returns empty capabilities."""
    _create_mock_package(tmp_path, "test_empty_pkg", {})
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server("test_empty_pkg")
        responses = await _send_and_collect(server, [
            {"jsonrpc": "2.0", "method": "describe", "id": 1},
        ])

        assert len(responses) == 1
        resp = responses[0]
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert "result" in resp
        caps = resp["result"]["capabilities"]
        assert caps["tools"] == []
        assert caps["hooks"] == []
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("test_empty_pkg"):
                del sys.modules[key]


async def test_describe_with_tool(tmp_path: Path):
    """describe returns discovered tools."""
    _create_mock_package(
        tmp_path,
        "test_tool_pkg",
        {
            "tools/adder.py": """\
                from amplifier_ipc_protocol.decorators import tool

                @tool
                class AdderTool:
                    name = "adder"
                    description = "Adds numbers"
                    input_schema = {"type": "object", "properties": {"a": {"type": "number"}}}

                    async def execute(self, input):
                        return None
            """,
        },
    )
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server("test_tool_pkg")
        responses = await _send_and_collect(server, [
            {"jsonrpc": "2.0", "method": "describe", "id": 1},
        ])

        caps = responses[0]["result"]["capabilities"]
        assert len(caps["tools"]) == 1
        assert caps["tools"][0]["name"] == "adder"
        assert caps["tools"][0]["description"] == "Adds numbers"
        assert "input_schema" in caps["tools"][0]
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("test_tool_pkg"):
                del sys.modules[key]


async def test_describe_with_content(tmp_path: Path):
    """describe returns content paths."""
    _create_mock_package(
        tmp_path,
        "test_content_pkg",
        {
            "agents/explorer.md": "# Explorer",
            "context/rules.md": "# Rules",
        },
    )
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server("test_content_pkg")
        responses = await _send_and_collect(server, [
            {"jsonrpc": "2.0", "method": "describe", "id": 1},
        ])

        content = responses[0]["result"]["capabilities"]["content"]
        paths = content["paths"]
        assert any("explorer.md" in p for p in paths)
        assert any("rules.md" in p for p in paths)
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("test_content_pkg"):
                del sys.modules[key]


# ── content.read ─────────────────────────────────────────────────────────


async def test_content_read(tmp_path: Path):
    """content.read returns file contents."""
    _create_mock_package(
        tmp_path,
        "test_read_pkg",
        {"agents/explorer.md": "# Explorer Agent\n\nDoes exploring."},
    )
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server("test_read_pkg")
        responses = await _send_and_collect(server, [
            {
                "jsonrpc": "2.0",
                "method": "content.read",
                "params": {"path": "agents/explorer.md"},
                "id": 1,
            },
        ])

        assert responses[0]["id"] == 1
        assert "# Explorer Agent" in responses[0]["result"]["content"]
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("test_read_pkg"):
                del sys.modules[key]


async def test_content_read_not_found(tmp_path: Path):
    """content.read for a missing file returns an error."""
    _create_mock_package(tmp_path, "test_missing_pkg", {})
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server("test_missing_pkg")
        responses = await _send_and_collect(server, [
            {
                "jsonrpc": "2.0",
                "method": "content.read",
                "params": {"path": "agents/nonexistent.md"},
                "id": 1,
            },
        ])

        assert "error" in responses[0]
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("test_missing_pkg"):
                del sys.modules[key]


# ── content.list ─────────────────────────────────────────────────────────


async def test_content_list(tmp_path: Path):
    """content.list returns available content paths."""
    _create_mock_package(
        tmp_path,
        "test_list_pkg",
        {
            "agents/explorer.md": "# Explorer",
            "agents/planner.md": "# Planner",
            "context/rules.md": "# Rules",
        },
    )
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server("test_list_pkg")
        responses = await _send_and_collect(server, [
            {"jsonrpc": "2.0", "method": "content.list", "id": 1},
        ])

        paths = responses[0]["result"]["paths"]
        assert len(paths) == 3
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("test_list_pkg"):
                del sys.modules[key]


# ── Method not found ─────────────────────────────────────────────────────


async def test_method_not_found(tmp_path: Path):
    """Unknown method returns a METHOD_NOT_FOUND error."""
    _create_mock_package(tmp_path, "test_notfound_pkg", {})
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server("test_notfound_pkg")
        responses = await _send_and_collect(server, [
            {"jsonrpc": "2.0", "method": "nonexistent.method", "id": 1},
        ])

        assert "error" in responses[0]
        assert responses[0]["error"]["code"] == -32601
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("test_notfound_pkg"):
                del sys.modules[key]


# ── tool.execute dispatch ────────────────────────────────────────────────


async def test_tool_execute(tmp_path: Path):
    """tool.execute dispatches to the named tool."""
    _create_mock_package(
        tmp_path,
        "test_exec_pkg",
        {
            "tools/adder.py": """\
                from amplifier_ipc_protocol.decorators import tool
                from amplifier_ipc_protocol.models import ToolResult

                @tool
                class AdderTool:
                    name = "adder"
                    description = "Adds a and b"
                    input_schema = {"type": "object"}

                    async def execute(self, input):
                        result = input.get("a", 0) + input.get("b", 0)
                        return ToolResult(success=True, output=result)
            """,
        },
    )
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server("test_exec_pkg")
        responses = await _send_and_collect(server, [
            {
                "jsonrpc": "2.0",
                "method": "tool.execute",
                "params": {"name": "adder", "input": {"a": 3, "b": 4}},
                "id": 1,
            },
        ])

        result = responses[0]["result"]
        assert result["success"] is True
        assert result["output"] == 7
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("test_exec_pkg"):
                del sys.modules[key]
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_server.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_protocol.server'`

**Step 3: Write the content module**

Create `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/content.py`:

```python
"""Content file discovery and serving from package data directories.

Content files live in conventional directories within a service package:
``agents/``, ``context/``, ``behaviors/``, ``recipes/``, ``sessions/``.
This module reads and lists those files for the server to serve.
"""

from __future__ import annotations

from pathlib import Path


def read_content(package_dir: Path, relative_path: str) -> str | None:
    """Read a content file from the package.

    Args:
        package_dir: Absolute path to the package root directory.
        relative_path: Path relative to the package root
                       (e.g., ``"agents/explorer.md"``).

    Returns:
        File content as a string, or None if the file doesn't exist
        or the path escapes the package directory.
    """
    target = (package_dir / relative_path).resolve()

    # Security: ensure the resolved path is under the package dir
    try:
        target.relative_to(package_dir.resolve())
    except ValueError:
        return None

    if not target.is_file():
        return None

    return target.read_text(encoding="utf-8")
```

**Step 4: Write the server module**

Create `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/server.py`:

```python
"""Generic JSON-RPC 2.0 server for amplifier IPC services.

The ``Server`` class handles:

- Stdin read loop and JSON-RPC framing
- Method dispatch to handler methods
- Component discovery (scan package for decorated classes)
- ``describe`` response generation from discovered components
- ``content.read`` / ``content.list`` from package data directories
- ``tool.execute`` dispatch to discovered tool instances
- ``hook.emit`` dispatch to discovered hook instances

Every service package creates a Server with its package name and runs it.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import sys
from pathlib import Path
from typing import Any

from amplifier_ipc_protocol.content import read_content
from amplifier_ipc_protocol.discovery import scan_content, scan_package
from amplifier_ipc_protocol.errors import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    JsonRpcError,
    make_error_response,
)
from amplifier_ipc_protocol.framing import read_message, write_message
from amplifier_ipc_protocol.models import HookAction, HookResult

logger = logging.getLogger(__name__)


class Server:
    """Generic JSON-RPC 2.0 server with component discovery.

    Args:
        package_name: Importable package name to scan for components
                      and content (e.g., ``"amplifier_foundation"``).
    """

    def __init__(self, package_name: str) -> None:
        self.package_name = package_name

        # Discover components and content
        self._components = scan_package(package_name)
        self._content_paths = scan_content(package_name)

        # Resolve the package directory for content serving
        mod = importlib.import_module(package_name)
        self._package_dir = Path(mod.__file__).parent

        # Build lookup indexes
        self._tools: dict[str, Any] = {}
        for t in self._components.get("tool", []):
            self._tools[t.name] = t

        self._hooks: dict[str, list[Any]] = {}
        for h in self._components.get("hook", []):
            for event in getattr(h, "events", []):
                if event not in self._hooks:
                    self._hooks[event] = []
                self._hooks[event].append(h)
        # Sort hooks by priority within each event
        for event_hooks in self._hooks.values():
            event_hooks.sort(key=lambda h: getattr(h, "priority", 0))

    async def handle_stream(self, reader: Any, writer: Any) -> None:
        """Process JSON-RPC messages from reader, write responses to writer.

        Reads messages until EOF, dispatches each to the appropriate
        handler, and writes responses back.

        Args:
            reader: An ``asyncio.StreamReader``.
            writer: An ``asyncio.StreamWriter`` (or compatible).
        """
        while True:
            try:
                msg = await read_message(reader)
            except ValueError as exc:
                # Malformed JSON — send parse error
                from amplifier_ipc_protocol.errors import PARSE_ERROR

                resp = make_error_response(None, PARSE_ERROR, str(exc))
                await write_message(writer, resp)
                continue

            if msg is None:
                break  # EOF

            request_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params", {})

            if method is None:
                if request_id is not None:
                    resp = make_error_response(
                        request_id, -32600, "Invalid request: missing method"
                    )
                    await write_message(writer, resp)
                continue

            # Dispatch to handler
            try:
                result = await self._dispatch(method, params)
                if request_id is not None:
                    resp = {"jsonrpc": "2.0", "id": request_id, "result": result}
                    await write_message(writer, resp)
            except JsonRpcError as exc:
                if request_id is not None:
                    await write_message(writer, exc.to_response(request_id))
            except Exception as exc:
                logger.exception("Error handling method %s", method)
                if request_id is not None:
                    resp = make_error_response(
                        request_id, INTERNAL_ERROR, str(exc)
                    )
                    await write_message(writer, resp)

    async def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        """Dispatch a method call to the appropriate handler."""
        # Built-in handlers
        if method == "describe":
            return self._handle_describe()
        elif method == "content.read":
            return self._handle_content_read(params)
        elif method == "content.list":
            return self._handle_content_list(params)
        elif method == "tool.execute":
            return await self._handle_tool_execute(params)
        elif method == "hook.emit":
            return await self._handle_hook_emit(params)
        else:
            raise JsonRpcError(METHOD_NOT_FOUND, f"Method not found: {method}")

    def _handle_describe(self) -> dict[str, Any]:
        """Build the describe response from discovered components."""
        tools = []
        for t in self._components.get("tool", []):
            tools.append({
                "name": t.name,
                "description": getattr(t, "description", ""),
                "input_schema": getattr(t, "input_schema", {}),
            })

        hooks = []
        for h in self._components.get("hook", []):
            hooks.append({
                "name": h.name,
                "events": getattr(h, "events", []),
                "priority": getattr(h, "priority", 0),
            })

        orchestrators = []
        for o in self._components.get("orchestrator", []):
            orchestrators.append({"name": o.name})

        context_managers = []
        for cm in self._components.get("context_manager", []):
            context_managers.append({"name": cm.name})

        providers = []
        for p in self._components.get("provider", []):
            providers.append({"name": p.name})

        return {
            "name": self.package_name,
            "capabilities": {
                "orchestrators": orchestrators,
                "context_managers": context_managers,
                "tools": tools,
                "hooks": hooks,
                "providers": providers,
                "content": {
                    "paths": self._content_paths,
                },
            },
        }

    def _handle_content_read(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read a content file from the package."""
        path = params.get("path")
        if not path:
            raise JsonRpcError(INVALID_PARAMS, "Missing 'path' parameter")

        content = read_content(self._package_dir, path)
        if content is None:
            raise JsonRpcError(INVALID_PARAMS, f"Content not found: {path}")

        return {"content": content}

    def _handle_content_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """List available content paths."""
        prefix = params.get("prefix")
        paths = self._content_paths
        if prefix:
            paths = [p for p in paths if p.startswith(prefix)]
        return {"paths": paths}

    async def _handle_tool_execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool by name."""
        name = params.get("name")
        if not name:
            raise JsonRpcError(INVALID_PARAMS, "Missing 'name' parameter")

        tool = self._tools.get(name)
        if tool is None:
            raise JsonRpcError(INVALID_PARAMS, f"Unknown tool: {name}")

        tool_input = params.get("input", {})
        result = await tool.execute(tool_input)

        # Return as dict for JSON serialization
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        return {"success": True, "output": result}

    async def _handle_hook_emit(self, params: dict[str, Any]) -> dict[str, Any]:
        """Emit a hook event to all registered hooks."""
        event = params.get("event")
        if not event:
            raise JsonRpcError(INVALID_PARAMS, "Missing 'event' parameter")

        data = params.get("data", {})
        handlers = self._hooks.get(event, [])

        if not handlers:
            return HookResult(action=HookAction.CONTINUE).model_dump(mode="json")

        current_data = data
        for hook in handlers:
            try:
                result = await hook.handle(event, current_data)
                if hasattr(result, "action"):
                    if result.action in (HookAction.DENY, HookAction.ASK_USER):
                        return result.model_dump(mode="json")
                    if result.action == HookAction.MODIFY and result.data is not None:
                        current_data = result.data
            except Exception:
                logger.warning(
                    "Error in hook %s for event %s",
                    getattr(hook, "name", "?"),
                    event,
                    exc_info=True,
                )

        return HookResult(action=HookAction.CONTINUE).model_dump(mode="json")

    async def run(self) -> None:
        """Run the server, reading from stdin and writing to stdout.

        This is the main entry point for service processes.
        """
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        # For stdout, we use a simple wrapper
        transport, _ = await loop.connect_write_pipe(
            asyncio.Protocol, sys.stdout.buffer
        )
        writer = _StdoutWriter(transport)

        await self.handle_stream(reader, writer)


class _StdoutWriter:
    """Minimal writer wrapper around a write transport."""

    def __init__(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport

    def write(self, data: bytes) -> None:
        self._transport.write(data)  # type: ignore[attr-defined]

    async def drain(self) -> None:
        # Write pipes don't need drain in practice
        pass
```

**Step 5: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_server.py -v
```
Expected: All tests PASS.

**Step 6: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc && git add amplifier-ipc-protocol/src/amplifier_ipc_protocol/content.py amplifier-ipc-protocol/src/amplifier_ipc_protocol/server.py amplifier-ipc-protocol/tests/test_server.py && git commit -m "feat: add generic Server with describe, content serving, and tool dispatch"
```

---

### Task 10: Integration Test and Public Exports

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-protocol/tests/test_integration.py`
- Modify: `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/__init__.py`

**Context:** This task proves the entire stack works end-to-end: Server + Client communicating over asyncio pipes. It also updates `__init__.py` to export the public API so users can write `from amplifier_ipc_protocol import tool, Server, Client, ...`.

**Step 1: Write the integration test**

Create `amplifier-ipc/amplifier-ipc-protocol/tests/test_integration.py`:

```python
"""Integration test — Server and Client talking over asyncio pipes."""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from amplifier_ipc_protocol.client import Client
from amplifier_ipc_protocol.server import Server


# ── Helpers ──────────────────────────────────────────────────────────────


def _create_mock_package(tmp_path: Path, pkg_name: str, files: dict[str, str]) -> None:
    """Create a mock Python package with given files."""
    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("")

    for rel_path, content in files.items():
        target = pkg_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix == ".py":
            init = target.parent / "__init__.py"
            if not init.exists():
                init.write_text("")
        target.write_text(textwrap.dedent(content))


def _create_connected_pair() -> tuple[
    asyncio.StreamReader,
    Any,
    asyncio.StreamReader,
    Any,
]:
    """Create two connected reader/writer pairs for in-process IPC.

    Returns (client_reader, client_writer, server_reader, server_writer)
    where:
    - client writes to server_reader
    - server writes to client_reader
    """
    client_reader = asyncio.StreamReader()
    server_reader = asyncio.StreamReader()

    class PipeWriter:
        def __init__(self, target_reader: asyncio.StreamReader):
            self._target = target_reader

        def write(self, data: bytes) -> None:
            self._target.feed_data(data)

        async def drain(self) -> None:
            pass

        def feed_eof(self) -> None:
            self._target.feed_eof()

    client_writer = PipeWriter(server_reader)
    server_writer = PipeWriter(client_reader)

    return client_reader, client_writer, server_reader, server_writer


# ── End-to-end test ──────────────────────────────────────────────────────


async def test_client_server_describe(tmp_path: Path):
    """Client sends describe to Server and gets capabilities back."""
    _create_mock_package(
        tmp_path,
        "test_integ_pkg",
        {
            "tools/adder.py": """\
                from amplifier_ipc_protocol.decorators import tool
                from amplifier_ipc_protocol.models import ToolResult

                @tool
                class AdderTool:
                    name = "adder"
                    description = "Adds two numbers"
                    input_schema = {"type": "object"}

                    async def execute(self, input):
                        return ToolResult(success=True, output=input["a"] + input["b"])
            """,
            "agents/test.md": "# Test Agent",
        },
    )
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server("test_integ_pkg")
        client_reader, client_writer, server_reader, server_writer = (
            _create_connected_pair()
        )

        # Run server in background
        server_task = asyncio.create_task(
            server.handle_stream(server_reader, server_writer)
        )

        # Create client
        client = Client(client_reader, client_writer)

        # Send describe
        result = await asyncio.wait_for(client.request("describe", {}), timeout=2.0)

        assert result["name"] == "test_integ_pkg"
        assert len(result["capabilities"]["tools"]) == 1
        assert result["capabilities"]["tools"][0]["name"] == "adder"
        assert any(
            "test.md" in p for p in result["capabilities"]["content"]["paths"]
        )

        # Clean up: close the connection so server exits
        client_writer.feed_eof()
        await asyncio.wait_for(server_task, timeout=2.0)
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("test_integ_pkg"):
                del sys.modules[key]


async def test_client_server_tool_execute(tmp_path: Path):
    """Client executes a tool through the Server and gets the result."""
    _create_mock_package(
        tmp_path,
        "test_integ_exec_pkg",
        {
            "tools/adder.py": """\
                from amplifier_ipc_protocol.decorators import tool
                from amplifier_ipc_protocol.models import ToolResult

                @tool
                class AdderTool:
                    name = "adder"
                    description = "Adds two numbers"
                    input_schema = {"type": "object"}

                    async def execute(self, input):
                        return ToolResult(success=True, output=input["a"] + input["b"])
            """,
        },
    )
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server("test_integ_exec_pkg")
        client_reader, client_writer, server_reader, server_writer = (
            _create_connected_pair()
        )

        server_task = asyncio.create_task(
            server.handle_stream(server_reader, server_writer)
        )

        client = Client(client_reader, client_writer)

        # Execute the adder tool
        result = await asyncio.wait_for(
            client.request("tool.execute", {"name": "adder", "input": {"a": 10, "b": 32}}),
            timeout=2.0,
        )

        assert result["success"] is True
        assert result["output"] == 42

        client_writer.feed_eof()
        await asyncio.wait_for(server_task, timeout=2.0)
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("test_integ_exec_pkg"):
                del sys.modules[key]


async def test_client_server_content_read(tmp_path: Path):
    """Client reads content through the Server."""
    _create_mock_package(
        tmp_path,
        "test_integ_content_pkg",
        {"agents/explorer.md": "# Explorer\n\nThis agent explores."},
    )
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server("test_integ_content_pkg")
        client_reader, client_writer, server_reader, server_writer = (
            _create_connected_pair()
        )

        server_task = asyncio.create_task(
            server.handle_stream(server_reader, server_writer)
        )

        client = Client(client_reader, client_writer)

        result = await asyncio.wait_for(
            client.request("content.read", {"path": "agents/explorer.md"}),
            timeout=2.0,
        )

        assert "# Explorer" in result["content"]

        client_writer.feed_eof()
        await asyncio.wait_for(server_task, timeout=2.0)
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("test_integ_content_pkg"):
                del sys.modules[key]


async def test_client_server_multiple_requests(tmp_path: Path):
    """Client sends multiple sequential requests over one connection."""
    _create_mock_package(
        tmp_path,
        "test_integ_multi_pkg",
        {
            "tools/adder.py": """\
                from amplifier_ipc_protocol.decorators import tool
                from amplifier_ipc_protocol.models import ToolResult

                @tool
                class AdderTool:
                    name = "adder"
                    description = "Adds two numbers"
                    input_schema = {"type": "object"}

                    async def execute(self, input):
                        return ToolResult(success=True, output=input["a"] + input["b"])
            """,
        },
    )
    sys.path.insert(0, str(tmp_path))
    try:
        server = Server("test_integ_multi_pkg")
        client_reader, client_writer, server_reader, server_writer = (
            _create_connected_pair()
        )

        server_task = asyncio.create_task(
            server.handle_stream(server_reader, server_writer)
        )

        client = Client(client_reader, client_writer)

        # First: describe
        desc = await asyncio.wait_for(client.request("describe", {}), timeout=2.0)
        assert desc["name"] == "test_integ_multi_pkg"

        # Second: tool execute
        result = await asyncio.wait_for(
            client.request("tool.execute", {"name": "adder", "input": {"a": 1, "b": 2}}),
            timeout=2.0,
        )
        assert result["output"] == 3

        # Third: content list
        listing = await asyncio.wait_for(
            client.request("content.list", {}), timeout=2.0
        )
        assert isinstance(listing["paths"], list)

        client_writer.feed_eof()
        await asyncio.wait_for(server_task, timeout=2.0)
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("test_integ_multi_pkg"):
                del sys.modules[key]
```

**Step 2: Run integration tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/test_integration.py -v
```
Expected: Should PASS (all implementation is already done from previous tasks). If any tests fail, fix the underlying implementation.

**Step 3: Update __init__.py with public exports**

Replace `amplifier-ipc/amplifier-ipc-protocol/src/amplifier_ipc_protocol/__init__.py` with:

```python
"""amplifier-ipc-protocol: Shared JSON-RPC 2.0 library for amplifier IPC services.

Public API
----------

Decorators (mark component classes for discovery)::

    from amplifier_ipc_protocol import tool, hook, orchestrator, context_manager, provider

Models (wire-format data types)::

    from amplifier_ipc_protocol import (
        ToolCall, ToolSpec, ToolResult, Message,
        HookAction, HookResult,
        ChatRequest, ChatResponse,
        TextBlock, ThinkingBlock, ToolCallBlock, Usage,
    )

Protocols (interface contracts for type checking)::

    from amplifier_ipc_protocol import (
        ToolProtocol, HookProtocol, OrchestratorProtocol,
        ContextManagerProtocol, ProviderProtocol,
    )

Infrastructure (for building services)::

    from amplifier_ipc_protocol import Server, Client, JsonRpcError
"""

from amplifier_ipc_protocol.client import Client
from amplifier_ipc_protocol.decorators import (
    context_manager,
    hook,
    orchestrator,
    provider,
    tool,
)
from amplifier_ipc_protocol.errors import JsonRpcError
from amplifier_ipc_protocol.models import (
    ChatRequest,
    ChatResponse,
    HookAction,
    HookResult,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolCallBlock,
    ToolResult,
    ToolSpec,
    Usage,
)
from amplifier_ipc_protocol.protocols import (
    ContextManagerProtocol,
    HookProtocol,
    OrchestratorProtocol,
    ProviderProtocol,
    ToolProtocol,
)
from amplifier_ipc_protocol.server import Server

__all__ = [
    # Decorators
    "tool",
    "hook",
    "orchestrator",
    "context_manager",
    "provider",
    # Models
    "ToolCall",
    "ToolSpec",
    "ToolResult",
    "Message",
    "HookAction",
    "HookResult",
    "ChatRequest",
    "ChatResponse",
    "TextBlock",
    "ThinkingBlock",
    "ToolCallBlock",
    "Usage",
    # Protocols
    "ToolProtocol",
    "HookProtocol",
    "OrchestratorProtocol",
    "ContextManagerProtocol",
    "ProviderProtocol",
    # Infrastructure
    "Server",
    "Client",
    "JsonRpcError",
]
```

**Step 4: Run the full test suite**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/ -v
```
Expected: ALL tests across all test files PASS.

**Step 5: Verify public imports work**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -c "
from amplifier_ipc_protocol import (
    tool, hook, orchestrator, context_manager, provider,
    Server, Client, JsonRpcError,
    ToolResult, HookResult, Message, ChatRequest, ChatResponse,
    ToolProtocol, HookProtocol, OrchestratorProtocol,
)
print('All imports OK')
"
```
Expected: `All imports OK`

**Step 6: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc && git add amplifier-ipc-protocol/tests/test_integration.py amplifier-ipc-protocol/src/amplifier_ipc_protocol/__init__.py && git commit -m "feat: add integration tests and public API exports"
```

---

## Verification Checklist

After all 10 tasks are complete, verify:

1. **Full test suite passes:**
   ```bash
   cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/ -v
   ```

2. **All source files exist:**
   ```
   src/amplifier_ipc_protocol/__init__.py
   src/amplifier_ipc_protocol/framing.py
   src/amplifier_ipc_protocol/errors.py
   src/amplifier_ipc_protocol/models.py
   src/amplifier_ipc_protocol/decorators.py
   src/amplifier_ipc_protocol/protocols.py
   src/amplifier_ipc_protocol/discovery.py
   src/amplifier_ipc_protocol/client.py
   src/amplifier_ipc_protocol/server.py
   src/amplifier_ipc_protocol/content.py
   ```

3. **All test files exist:**
   ```
   tests/test_framing.py
   tests/test_errors.py
   tests/test_models.py
   tests/test_decorators.py
   tests/test_protocols.py
   tests/test_discovery.py
   tests/test_client.py
   tests/test_server.py
   tests/test_integration.py
   ```

4. **Public API imports cleanly** (the `python -c` command from Step 5 of Task 10)

5. **10 git commits** (one per task)

## What's Next (Phase 2)

With this protocol library built and tested, Phase 2 builds `amplifier-ipc-host` — the message bus that spawns services, routes messages, fans out hooks, resolves content, and manages session lifecycle. The host depends on `amplifier-ipc-protocol` for framing, models, and the Client class.