# Anthropic Provider Full Port — Phase 2 Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Replace the Anthropic provider stub with a fully functional provider faithfully ported from the upstream pattern, serving as the reference implementation for all other providers in Phase 3.

**Architecture:** The Anthropic provider converts between Amplifier's data models (`ChatRequest`, `ChatResponse`, `Message`, `ToolCall`, `TextBlock`, `ThinkingBlock`, `ToolCallBlock`, `Usage`) and the Anthropic SDK's format (`anthropic.AsyncAnthropic`, `client.messages.create()`). It follows the same `@provider` decorator pattern as the mock provider but makes real API calls with retry logic, rate limiting, error translation, prompt caching, extended thinking, and tool-result repair.

**Tech Stack:** Python 3.11+, `anthropic` SDK, `amplifier-ipc-protocol` (Pydantic v2 models, `@provider` decorator), `pytest` + `pytest-asyncio`

---

## Verified Paths and Conventions

These paths and patterns were verified by reading the codebase:

| Item | Path |
|---|---|
| Provider stub to replace | `services/amplifier-providers/src/amplifier_providers/providers/anthropic_provider.py` |
| Mock provider (reference pattern) | `services/amplifier-providers/src/amplifier_providers/providers/mock.py` |
| Protocol models | `amplifier-ipc-protocol/src/amplifier_ipc_protocol/models.py` |
| Protocol `__init__.py` (public API) | `amplifier-ipc-protocol/src/amplifier_ipc_protocol/__init__.py` |
| Provider pyproject.toml | `services/amplifier-providers/pyproject.toml` |
| Test directory | `services/amplifier-providers/tests/` |
| Existing tests | `tests/test_scaffolding.py`, `tests/test_describe.py`, `tests/test_mock_provider.py` |

**Import pattern** (from mock provider):
```python
from amplifier_ipc_protocol import ChatRequest, ChatResponse, TextBlock, ToolCall, Usage, provider
from amplifier_ipc_protocol import Message, ThinkingBlock, ToolCallBlock, ToolSpec
```

**Provider class pattern** (from mock provider):
```python
@provider
class MockProvider:
    name = "mock"
    def __init__(self, config: dict | None = None) -> None: ...
    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse: ...
```

**Test pattern** (from `test_mock_provider.py`):
```python
from amplifier_ipc_protocol import ChatRequest, ChatResponse, Message
from amplifier_providers.providers.mock import MockProvider

async def test_mock_provider_complete_returns_chat_response() -> None:
    provider = MockProvider()
    request = ChatRequest(messages=[Message(role="user", content="Hello")])
    response = await provider.complete(request)
    assert isinstance(response, ChatResponse)
```

**Existing test that must be updated** (`test_describe.py` line 88–116):
`test_stub_providers_raise_not_implemented` asserts that `AnthropicProvider.complete()` raises `NotImplementedError`. After Phase 2, this assertion must change — Anthropic will no longer be a stub. The test checks all 7 stubs; we need to remove Anthropic from that list.

---

## Scope Boundaries

**Phase 2 INCLUDES:**
- Complete Anthropic provider: `__init__`, `_convert_messages()`, `_convert_tools_from_request()`, `_convert_to_chat_response()`, `complete()`
- Error handling and retry logic (Anthropic SDK errors → LLM errors)
- Rate limit tracking (pre-emptive throttling via response headers)
- Extended thinking support (thinking_budget, ThinkingBlock in response)
- Prompt caching (cache_control on system blocks)
- Tool-result repair (inject synthetic error results for missing tool_results)
- Unit tests for all conversion functions
- Integration test through IPC Server path
- README.md documenting dropped methods and configuration

**Phase 2 DOES NOT INCLUDE:**
- Provider streaming (designed in Phase 1 protocol, not implemented here — `complete()` returns full response)
- Other providers (Phase 3)
- End-to-end smoke test (Phase 3)

---

### Task 1: Port `_convert_messages()` — Amplifier → Anthropic format

**Files:**
- Modify: `services/amplifier-providers/src/amplifier_providers/providers/anthropic_provider.py`
- Create: `services/amplifier-providers/tests/test_anthropic_provider.py`

This is the most complex conversion. Anthropic's Messages API expects a specific format for messages that differs from Amplifier's internal representation.

**Step 1: Write the failing tests**

Create `services/amplifier-providers/tests/test_anthropic_provider.py`:

```python
"""Tests for AnthropicProvider conversion logic."""

from __future__ import annotations

from typing import Any

import pytest

from amplifier_ipc_protocol import (
    ChatRequest,
    ChatResponse,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolCallBlock,
    ToolSpec,
    Usage,
)


# ---------------------------------------------------------------------------
# _convert_messages tests
# ---------------------------------------------------------------------------


class TestConvertMessages:
    """Tests for _convert_messages: Amplifier Message list → Anthropic API format."""

    def _make_provider(self) -> Any:
        """Create a provider instance without requiring an API key."""
        from amplifier_providers.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(config={"api_key": "test-key"})

    def test_simple_user_message(self) -> None:
        """A single user message with string content."""
        p = self._make_provider()
        messages = [Message(role="user", content="Hello")]
        result = p._convert_messages(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"

    def test_user_assistant_alternation(self) -> None:
        """User/assistant messages convert directly."""
        p = self._make_provider()
        messages = [
            Message(role="user", content="Hi"),
            Message(role="assistant", content="Hello!"),
            Message(role="user", content="How are you?"),
        ]
        result = p._convert_messages(messages)
        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "user"

    def test_system_messages_excluded(self) -> None:
        """System messages are NOT included in converted messages (handled separately)."""
        p = self._make_provider()
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hello"),
        ]
        result = p._convert_messages(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_tool_result_message(self) -> None:
        """Tool result messages convert to Anthropic tool_result content blocks."""
        p = self._make_provider()
        messages = [
            Message(
                role="user",
                content="Read the file",
            ),
            Message(
                role="assistant",
                content=[
                    ToolCallBlock(id="tc_1", name="read_file", input={"path": "test.txt"})
                ],
            ),
            Message(
                role="tool",
                content="file contents here",
                tool_call_id="tc_1",
                name="read_file",
            ),
        ]
        result = p._convert_messages(messages)
        # The tool result should be converted to a user message with tool_result block
        tool_result_msg = result[2]
        assert tool_result_msg["role"] == "user"
        assert isinstance(tool_result_msg["content"], list)
        assert tool_result_msg["content"][0]["type"] == "tool_result"
        assert tool_result_msg["content"][0]["tool_use_id"] == "tc_1"

    def test_assistant_with_tool_calls(self) -> None:
        """Assistant messages with tool_calls produce tool_use content blocks."""
        p = self._make_provider()
        messages = [
            Message(
                role="assistant",
                content=[
                    TextBlock(text="I'll read that."),
                    ToolCallBlock(id="tc_1", name="read_file", input={"path": "x.txt"}),
                ],
            ),
        ]
        result = p._convert_messages(messages)
        assert len(result) == 1
        assistant_content = result[0]["content"]
        assert any(b["type"] == "text" for b in assistant_content)
        assert any(b["type"] == "tool_use" for b in assistant_content)

    def test_developer_messages_become_xml_wrapped_user(self) -> None:
        """Developer messages are converted to XML-wrapped user messages."""
        p = self._make_provider()
        messages = [Message(role="developer", content="Context info here")]
        result = p._convert_messages(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        content = result[0]["content"]
        assert "<context_file>" in content or (
            isinstance(content, list) and "<context_file>" in str(content)
        )

    def test_thinking_block_in_assistant(self) -> None:
        """Assistant messages with ThinkingBlock are preserved for Anthropic."""
        p = self._make_provider()
        messages = [
            Message(
                role="assistant",
                content=[
                    ThinkingBlock(thinking="Let me think...", signature="sig123"),
                    TextBlock(text="Here's my answer."),
                ],
            ),
        ]
        result = p._convert_messages(messages)
        assert len(result) == 1
        blocks = result[0]["content"]
        assert any(b.get("type") == "thinking" for b in blocks)
        assert any(b.get("type") == "text" for b in blocks)
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_anthropic_provider.py -v
```

Expected: FAIL — `AnthropicProvider.__init__` doesn't accept config yet, `_convert_messages` doesn't exist.

**Step 3: Implement `_convert_messages` in the provider**

Replace the contents of `services/amplifier-providers/src/amplifier_providers/providers/anthropic_provider.py` with:

```python
"""Anthropic provider — faithful port from upstream amplifier-module-provider-anthropic.

Converts between Amplifier's data models (ChatRequest, ChatResponse, Message,
ToolCall, TextBlock, ThinkingBlock, ToolCallBlock, Usage) and the Anthropic
Messages API format.

Dropped from upstream (not in IPC protocol yet):
- get_info() — provider metadata
- list_models() — model discovery
- close() — client cleanup
- mount() — v1 lifecycle
- __amplifier_module_type__ — v1 module marker
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from amplifier_ipc_protocol import (
    ChatRequest,
    ChatResponse,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolCallBlock,
    ToolSpec,
    Usage,
    provider,
)

__all__ = ["AnthropicProvider"]

logger = logging.getLogger(__name__)

# Default model if none specified in config
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 16384


@provider
class AnthropicProvider:
    """Anthropic Messages API integration.

    Ported from upstream amplifier-module-provider-anthropic. Only IPC-required
    changes: imports swapped, lifecycle methods dropped, __init__ takes config dict.
    """

    name = "anthropic"

    def __init__(self, config: dict | None = None) -> None:
        """Initialize Anthropic provider.

        Args:
            config: Optional configuration dict. Reads api_key from
                    config["api_key"] or ANTHROPIC_API_KEY env var.
        """
        self.config = config or {}

        # API key: config > env var
        self._api_key = self.config.get("api_key") or os.environ.get(
            "ANTHROPIC_API_KEY"
        )

        # Lazy client init
        self._client = None

        # Model configuration
        self.default_model = self.config.get("model", DEFAULT_MODEL)
        self.max_tokens = self.config.get("max_tokens", DEFAULT_MAX_TOKENS)
        self.temperature = self.config.get("temperature", None)

        # Extended thinking
        self.thinking_budget = self.config.get("thinking_budget", None)

        # Track repaired tool call IDs to prevent infinite loops
        self._repaired_tool_ids: set[str] = set()

        # Rate limit state
        self._rate_limit_state = _RateLimitState()

    @property
    def client(self):
        """Lazily initialize the Anthropic async client."""
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:
                raise ImportError(
                    "The 'anthropic' package is required for the Anthropic provider. "
                    "Install it with: pip install amplifier-providers[anthropic]"
                ) from e

            if not self._api_key:
                raise ValueError(
                    "No API key found. Set ANTHROPIC_API_KEY env var or pass "
                    "config={'api_key': '...'} to the provider."
                )

            self._client = anthropic.AsyncAnthropic(
                api_key=self._api_key, max_retries=0
            )
        return self._client

    # ------------------------------------------------------------------
    # Message conversion: Amplifier → Anthropic
    # ------------------------------------------------------------------

    def _convert_messages(
        self, messages: list[Message]
    ) -> list[dict[str, Any]]:
        """Convert Amplifier Message list to Anthropic Messages API format.

        Handles:
        - User messages → {"role": "user", "content": ...}
        - Assistant messages → {"role": "assistant", "content": [...blocks...]}
        - Tool result messages → {"role": "user", "content": [{"type": "tool_result", ...}]}
        - Developer messages → XML-wrapped user messages
        - System messages → skipped (handled separately as system param)
        - ThinkingBlock → {"type": "thinking", ...} in assistant content
        - ToolCallBlock → {"type": "tool_use", ...} in assistant content

        Args:
            messages: Amplifier Message objects from ChatRequest.messages

        Returns:
            List of Anthropic-formatted message dicts
        """
        anthropic_messages: list[dict[str, Any]] = []
        i = 0

        while i < len(messages):
            msg = messages[i]

            # Skip system messages — handled via the system parameter
            if msg.role == "system":
                i += 1
                continue

            # Developer messages → XML-wrapped user messages
            if msg.role == "developer":
                content_str = msg.content if isinstance(msg.content, str) else ""
                wrapped = f"<context_file>\n{content_str}\n</context_file>"
                anthropic_messages.append({"role": "user", "content": wrapped})
                i += 1
                continue

            # Tool result messages → user message with tool_result blocks
            if msg.role == "tool":
                tool_result_blocks: list[dict[str, Any]] = []

                while i < len(messages) and messages[i].role == "tool":
                    tool_msg = messages[i]
                    tool_call_id = tool_msg.tool_call_id or ""
                    tool_content = tool_msg.content

                    # Serialize content to string
                    if isinstance(tool_content, str):
                        content_str = tool_content
                    elif isinstance(tool_content, (dict, list)):
                        content_str = json.dumps(tool_content)
                    else:
                        content_str = str(tool_content) if tool_content else ""

                    tool_result_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_call_id,
                            "content": content_str,
                        }
                    )
                    i += 1

                anthropic_messages.append(
                    {"role": "user", "content": tool_result_blocks}
                )
                continue

            # Assistant messages → content blocks
            if msg.role == "assistant":
                content_blocks = self._convert_assistant_content(msg)
                anthropic_messages.append(
                    {"role": "assistant", "content": content_blocks}
                )
                i += 1
                continue

            # User messages — pass through
            if msg.role == "user":
                if isinstance(msg.content, str):
                    anthropic_messages.append(
                        {"role": "user", "content": msg.content}
                    )
                elif isinstance(msg.content, list):
                    # Structured content blocks
                    content_blocks = []
                    for block in msg.content:
                        if hasattr(block, "type"):
                            if block.type == "text":
                                content_blocks.append(
                                    {"type": "text", "text": getattr(block, "text", "")}
                                )
                            elif block.type == "image":
                                # Image blocks — convert to Anthropic format
                                source = getattr(block, "source", {})
                                if isinstance(source, dict):
                                    content_blocks.append(
                                        {
                                            "type": "image",
                                            "source": source,
                                        }
                                    )
                        elif isinstance(block, dict):
                            content_blocks.append(block)
                    anthropic_messages.append(
                        {"role": "user", "content": content_blocks}
                    )
                else:
                    anthropic_messages.append(
                        {"role": "user", "content": str(msg.content or "")}
                    )
                i += 1
                continue

            # Unknown role — skip with warning
            logger.warning("Unknown message role: %s", msg.role)
            i += 1

        return anthropic_messages

    def _convert_assistant_content(
        self, msg: Message
    ) -> list[dict[str, Any]]:
        """Convert an assistant message's content to Anthropic content blocks.

        Handles:
        - str content → [{"type": "text", "text": ...}]
        - list content with TextBlock → {"type": "text", ...}
        - list content with ThinkingBlock → {"type": "thinking", ...}
        - list content with ToolCallBlock → {"type": "tool_use", ...}
        - tool_calls field → {"type": "tool_use", ...}
        """
        blocks: list[dict[str, Any]] = []

        if isinstance(msg.content, str) and msg.content:
            blocks.append({"type": "text", "text": msg.content})
        elif isinstance(msg.content, list):
            for block in msg.content:
                if hasattr(block, "type"):
                    if block.type == "text":
                        text = getattr(block, "text", "")
                        if text:
                            blocks.append({"type": "text", "text": text})
                    elif block.type == "thinking":
                        thinking_text = getattr(block, "thinking", "")
                        signature = getattr(block, "signature", None)
                        thinking_block: dict[str, Any] = {
                            "type": "thinking",
                            "thinking": thinking_text,
                        }
                        if signature:
                            thinking_block["signature"] = signature
                        blocks.append(thinking_block)
                    elif block.type == "tool_call":
                        tc_id = getattr(block, "id", "")
                        tc_name = getattr(block, "name", "")
                        tc_input = getattr(block, "input", {})
                        blocks.append(
                            {
                                "type": "tool_use",
                                "id": tc_id,
                                "name": tc_name,
                                "input": tc_input if isinstance(tc_input, dict) else {},
                            }
                        )
                elif isinstance(block, dict):
                    block_type = block.get("type")
                    if block_type == "text":
                        blocks.append({"type": "text", "text": block.get("text", "")})
                    elif block_type == "thinking":
                        thinking_block = {
                            "type": "thinking",
                            "thinking": block.get("thinking", ""),
                        }
                        if block.get("signature"):
                            thinking_block["signature"] = block["signature"]
                        blocks.append(thinking_block)
                    elif block_type == "tool_call":
                        blocks.append(
                            {
                                "type": "tool_use",
                                "id": block.get("id", ""),
                                "name": block.get("name", ""),
                                "input": block.get("input", {}),
                            }
                        )

        # Also handle tool_calls field (from context storage)
        if msg.tool_calls:
            for tc in msg.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments if isinstance(tc.arguments, dict) else {},
                    }
                )

        # Ensure at least one block (Anthropic requires non-empty content)
        if not blocks:
            blocks.append({"type": "text", "text": ""})

        return blocks

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Not yet implemented — see Task 4."""
        raise NotImplementedError(
            "AnthropicProvider.complete() is not yet implemented. See Task 4."
        )


class _RateLimitState:
    """Tracks Anthropic rate limit headers for pre-emptive throttling."""

    def __init__(self) -> None:
        self.requests_limit: int | None = None
        self.requests_remaining: int | None = None
        self.requests_reset: str | None = None
        self.tokens_limit: int | None = None
        self.tokens_remaining: int | None = None
        self.tokens_reset: str | None = None
        self.retry_after: float | None = None
```

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_anthropic_provider.py -v
```

Expected: All `TestConvertMessages` tests PASS.

**Step 5: Run existing tests to verify no regressions**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/ -v
```

Expected: All existing tests PASS. Note: `test_stub_providers_raise_not_implemented` still passes because `complete()` still raises `NotImplementedError` (we haven't implemented it yet).

**Step 6: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/src/amplifier_providers/providers/anthropic_provider.py services/amplifier-providers/tests/test_anthropic_provider.py && git commit -m "feat(anthropic): port _convert_messages and _convert_assistant_content from upstream"
```

---

### Task 2: Port `_convert_tools_from_request()` and `_convert_to_chat_response()`

**Files:**
- Modify: `services/amplifier-providers/src/amplifier_providers/providers/anthropic_provider.py`
- Modify: `services/amplifier-providers/tests/test_anthropic_provider.py`

**Step 1: Write the failing tests**

Append to `services/amplifier-providers/tests/test_anthropic_provider.py`:

```python
# ---------------------------------------------------------------------------
# _convert_tools_from_request tests
# ---------------------------------------------------------------------------


class TestConvertToolsFromRequest:
    """Tests for _convert_tools_from_request: ToolSpec list → Anthropic format."""

    def _make_provider(self) -> Any:
        from amplifier_providers.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(config={"api_key": "test-key"})

    def test_single_tool(self) -> None:
        """A single ToolSpec converts to Anthropic tool format."""
        p = self._make_provider()
        tools = [
            ToolSpec(
                name="bash",
                description="Run shell commands",
                parameters={
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            )
        ]
        result = p._convert_tools_from_request(tools)
        assert len(result) == 1
        assert result[0]["name"] == "bash"
        assert result[0]["description"] == "Run shell commands"
        assert result[0]["input_schema"]["type"] == "object"
        assert "command" in result[0]["input_schema"]["properties"]

    def test_multiple_tools(self) -> None:
        """Multiple tools all convert correctly."""
        p = self._make_provider()
        tools = [
            ToolSpec(name="bash", description="Run commands", parameters={"type": "object"}),
            ToolSpec(name="read_file", description="Read files", parameters={"type": "object"}),
        ]
        result = p._convert_tools_from_request(tools)
        assert len(result) == 2
        names = {t["name"] for t in result}
        assert names == {"bash", "read_file"}

    def test_empty_tools(self) -> None:
        """Empty tool list returns empty list."""
        p = self._make_provider()
        result = p._convert_tools_from_request([])
        assert result == []

    def test_tool_with_empty_parameters(self) -> None:
        """Tools with empty parameters still get a valid input_schema."""
        p = self._make_provider()
        tools = [ToolSpec(name="foo", description="Does foo", parameters={})]
        result = p._convert_tools_from_request(tools)
        assert result[0]["input_schema"] == {}


# ---------------------------------------------------------------------------
# _convert_to_chat_response tests
# ---------------------------------------------------------------------------


class TestConvertToChatResponse:
    """Tests for _convert_to_chat_response: Anthropic response → ChatResponse."""

    def _make_provider(self) -> Any:
        from amplifier_providers.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(config={"api_key": "test-key"})

    def _make_anthropic_response(
        self,
        content: list[dict[str, Any]],
        *,
        model: str = "claude-sonnet-4-20250514",
        stop_reason: str = "end_turn",
        input_tokens: int = 100,
        output_tokens: int = 50,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> Any:
        """Create a mock Anthropic API response object."""

        class MockUsage:
            def __init__(self, inp: int, out: int, cache_create: int, cache_read: int):
                self.input_tokens = inp
                self.output_tokens = out
                self.cache_creation_input_tokens = cache_create
                self.cache_read_input_tokens = cache_read

        class MockResponse:
            def __init__(self, content, model, stop_reason, usage):
                self.id = "msg_test123"
                self.content = content
                self.model = model
                self.stop_reason = stop_reason
                self.usage = usage
                self.type = "message"

        # Convert dicts to mock objects with type/text/etc attributes
        content_objects = []
        for block in content:
            obj = type("Block", (), block)()
            content_objects.append(obj)

        usage = MockUsage(input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens)
        return MockResponse(content_objects, model, stop_reason, usage)

    def test_text_response(self) -> None:
        """Text-only response converts to ChatResponse with TextBlock content."""
        p = self._make_provider()
        response = self._make_anthropic_response(
            content=[{"type": "text", "text": "Hello world"}]
        )
        result = p._convert_to_chat_response(response)

        assert isinstance(result, ChatResponse)
        assert result.content is not None
        assert len(result.content) == 1
        assert result.content[0].type == "text"
        assert result.content[0].text == "Hello world"
        assert result.tool_calls is None or len(result.tool_calls) == 0

    def test_tool_use_response(self) -> None:
        """Response with tool_use block produces ToolCall in ChatResponse."""
        p = self._make_provider()
        response = self._make_anthropic_response(
            content=[
                {"type": "text", "text": "I'll read that."},
                {
                    "type": "tool_use",
                    "id": "toolu_123",
                    "name": "read_file",
                    "input": {"path": "test.txt"},
                },
            ],
            stop_reason="tool_use",
        )
        result = p._convert_to_chat_response(response)

        assert result.content is not None
        assert len(result.content) == 2
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "toolu_123"
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[0].arguments == {"path": "test.txt"}

    def test_thinking_response(self) -> None:
        """Response with thinking block produces ThinkingBlock in ChatResponse."""
        p = self._make_provider()
        response = self._make_anthropic_response(
            content=[
                {"type": "thinking", "thinking": "Let me reason...", "signature": "sig_abc"},
                {"type": "text", "text": "Here's the answer."},
            ]
        )
        result = p._convert_to_chat_response(response)

        assert result.content is not None
        assert len(result.content) == 2
        thinking = result.content[0]
        assert thinking.type == "thinking"
        assert thinking.thinking == "Let me reason..."

    def test_usage_extraction(self) -> None:
        """Usage tokens are correctly extracted from Anthropic response."""
        p = self._make_provider()
        response = self._make_anthropic_response(
            content=[{"type": "text", "text": "hi"}],
            input_tokens=200,
            output_tokens=100,
            cache_read_input_tokens=50,
        )
        result = p._convert_to_chat_response(response)

        assert result.usage is not None
        assert result.usage.input_tokens == 200
        assert result.usage.output_tokens == 100
        assert result.usage.total_tokens == 300
        assert result.usage.cache_read_tokens == 50

    def test_finish_reason_mapping(self) -> None:
        """Anthropic stop_reason is mapped to finish_reason."""
        p = self._make_provider()
        response = self._make_anthropic_response(
            content=[{"type": "text", "text": "done"}],
            stop_reason="end_turn",
        )
        result = p._convert_to_chat_response(response)
        assert result.finish_reason == "end_turn"
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_anthropic_provider.py::TestConvertToolsFromRequest -v
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_anthropic_provider.py::TestConvertToChatResponse -v
```

Expected: FAIL — methods don't exist yet.

**Step 3: Add `_convert_tools_from_request` and `_convert_to_chat_response` to the provider**

Add these methods to the `AnthropicProvider` class in `anthropic_provider.py`, after `_convert_assistant_content`:

```python
    # ------------------------------------------------------------------
    # Tool conversion: Amplifier ToolSpec → Anthropic tool format
    # ------------------------------------------------------------------

    def _convert_tools_from_request(
        self, tools: list[ToolSpec]
    ) -> list[dict[str, Any]]:
        """Convert Amplifier ToolSpec objects to Anthropic tool format.

        Args:
            tools: List of ToolSpec objects from ChatRequest.tools

        Returns:
            List of Anthropic-formatted tool definitions
        """
        anthropic_tools = []
        for tool in tools:
            anthropic_tools.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.parameters,
                }
            )
        return anthropic_tools

    # ------------------------------------------------------------------
    # Response conversion: Anthropic response → ChatResponse
    # ------------------------------------------------------------------

    def _convert_to_chat_response(self, response: Any) -> ChatResponse:
        """Convert Anthropic Messages API response to ChatResponse.

        Handles:
        - text blocks → TextBlock
        - thinking blocks → ThinkingBlock
        - tool_use blocks → ToolCallBlock + ToolCall
        - usage → Usage with cache tokens

        Args:
            response: Anthropic API response object

        Returns:
            ChatResponse with content blocks, tool calls, and usage
        """
        content_blocks: list[Any] = []
        tool_calls: list[ToolCall] = []

        for block in response.content:
            block_type = getattr(block, "type", None)

            if block_type == "text":
                text = getattr(block, "text", "")
                content_blocks.append(TextBlock(text=text))

            elif block_type == "thinking":
                thinking_text = getattr(block, "thinking", "")
                signature = getattr(block, "signature", None)
                content_blocks.append(
                    ThinkingBlock(
                        thinking=thinking_text,
                        signature=signature,
                    )
                )

            elif block_type == "tool_use":
                tc_id = getattr(block, "id", "")
                tc_name = getattr(block, "name", "")
                tc_input = getattr(block, "input", {})
                if not isinstance(tc_input, dict):
                    tc_input = {}

                content_blocks.append(
                    ToolCallBlock(id=tc_id, name=tc_name, input=tc_input)
                )
                tool_calls.append(
                    ToolCall(id=tc_id, name=tc_name, arguments=tc_input)
                )

        # Extract usage
        usage_obj = getattr(response, "usage", None)
        input_tokens = getattr(usage_obj, "input_tokens", 0) if usage_obj else 0
        output_tokens = getattr(usage_obj, "output_tokens", 0) if usage_obj else 0
        cache_creation = (
            getattr(usage_obj, "cache_creation_input_tokens", 0) if usage_obj else 0
        )
        cache_read = (
            getattr(usage_obj, "cache_read_input_tokens", 0) if usage_obj else 0
        )

        usage = Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cache_read_tokens=cache_read if cache_read else None,
            cache_write_tokens=cache_creation if cache_creation else None,
        )

        # Extract combined text for convenience
        text_parts = [
            b.text for b in content_blocks if hasattr(b, "text") and hasattr(b, "type") and b.type == "text"
        ]
        combined_text = "\n\n".join(text_parts).strip() or None

        return ChatResponse(
            content=content_blocks,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
            text=combined_text,
            finish_reason=getattr(response, "stop_reason", None),
            metadata={"model": getattr(response, "model", None)},
        )
```

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_anthropic_provider.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/src/amplifier_providers/providers/anthropic_provider.py services/amplifier-providers/tests/test_anthropic_provider.py && git commit -m "feat(anthropic): port _convert_tools_from_request and _convert_to_chat_response"
```

---

### Task 3: Port error handling and retry logic

**Files:**
- Modify: `services/amplifier-providers/src/amplifier_providers/providers/anthropic_provider.py`
- Modify: `services/amplifier-providers/tests/test_anthropic_provider.py`

The upstream provider translates Anthropic SDK exceptions into LLM error types and wraps API calls in retry-with-backoff logic. The IPC protocol doesn't have LLM error types, so we define a minimal set locally in the provider file.

**Step 1: Write the failing tests**

Append to `services/amplifier-providers/tests/test_anthropic_provider.py`:

```python
# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErrorTranslation:
    """Tests for Anthropic SDK error → provider error translation."""

    def _make_provider(self) -> Any:
        from amplifier_providers.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(config={"api_key": "test-key"})

    def test_translate_rate_limit_error(self) -> None:
        """Anthropic RateLimitError maps to retryable error with retry_after."""
        from amplifier_providers.providers.anthropic_provider import (
            _translate_anthropic_error,
        )
        import anthropic

        # Create a mock RateLimitError
        class MockResponse:
            status_code = 429
            headers = {"retry-after": "30"}

        try:
            raise anthropic.RateLimitError(
                message="Rate limited",
                response=MockResponse(),
                body={"error": {"message": "Rate limited"}},
            )
        except anthropic.RateLimitError as e:
            result = _translate_anthropic_error(e)
            assert result["retryable"] is True
            assert result["status_code"] == 429

    def test_translate_auth_error(self) -> None:
        """Anthropic AuthenticationError maps to non-retryable error."""
        from amplifier_providers.providers.anthropic_provider import (
            _translate_anthropic_error,
        )
        import anthropic

        class MockResponse:
            status_code = 401
            headers = {}

        try:
            raise anthropic.AuthenticationError(
                message="Invalid API key",
                response=MockResponse(),
                body={"error": {"message": "Invalid API key"}},
            )
        except anthropic.AuthenticationError as e:
            result = _translate_anthropic_error(e)
            assert result["retryable"] is False
            assert result["status_code"] == 401

    def test_translate_bad_request_error(self) -> None:
        """Anthropic BadRequestError maps to non-retryable error."""
        from amplifier_providers.providers.anthropic_provider import (
            _translate_anthropic_error,
        )
        import anthropic

        class MockResponse:
            status_code = 400
            headers = {}

        try:
            raise anthropic.BadRequestError(
                message="Invalid request",
                response=MockResponse(),
                body={"error": {"message": "Invalid request"}},
            )
        except anthropic.BadRequestError as e:
            result = _translate_anthropic_error(e)
            assert result["retryable"] is False
            assert result["status_code"] == 400

    def test_translate_overloaded_error(self) -> None:
        """Anthropic OverloadedError (529) maps to retryable error."""
        from amplifier_providers.providers.anthropic_provider import (
            _translate_anthropic_error,
        )
        import anthropic

        class MockResponse:
            status_code = 529
            headers = {}

        try:
            raise anthropic.APIStatusError(
                message="Overloaded",
                response=MockResponse(),
                body={"error": {"message": "Overloaded"}},
            )
        except anthropic.APIStatusError as e:
            result = _translate_anthropic_error(e)
            assert result["retryable"] is True
            assert result["status_code"] == 529


# ---------------------------------------------------------------------------
# Retry logic tests
# ---------------------------------------------------------------------------


class TestRetryWithBackoff:
    """Tests for retry_with_backoff helper."""

    async def test_succeeds_first_try(self) -> None:
        """Function that succeeds on first call is not retried."""
        from amplifier_providers.providers.anthropic_provider import retry_with_backoff

        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_with_backoff(fn, max_retries=3, initial_delay=0.01)
        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_retryable_error(self) -> None:
        """Function that fails with retryable error is retried."""
        from amplifier_providers.providers.anthropic_provider import (
            retry_with_backoff,
            ProviderError,
        )

        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ProviderError("fail", retryable=True)
            return "ok"

        result = await retry_with_backoff(fn, max_retries=5, initial_delay=0.01)
        assert result == "ok"
        assert call_count == 3

    async def test_gives_up_after_max_retries(self) -> None:
        """Function that always fails raises after max_retries."""
        from amplifier_providers.providers.anthropic_provider import (
            retry_with_backoff,
            ProviderError,
        )

        async def fn():
            raise ProviderError("always fail", retryable=True)

        with pytest.raises(ProviderError, match="always fail"):
            await retry_with_backoff(fn, max_retries=2, initial_delay=0.01)

    async def test_non_retryable_error_not_retried(self) -> None:
        """Non-retryable errors are raised immediately without retry."""
        from amplifier_providers.providers.anthropic_provider import (
            retry_with_backoff,
            ProviderError,
        )

        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            raise ProviderError("auth fail", retryable=False)

        with pytest.raises(ProviderError, match="auth fail"):
            await retry_with_backoff(fn, max_retries=5, initial_delay=0.01)
        assert call_count == 1
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_anthropic_provider.py::TestErrorTranslation -v
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_anthropic_provider.py::TestRetryWithBackoff -v
```

Expected: FAIL — `_translate_anthropic_error`, `retry_with_backoff`, `ProviderError` don't exist.

**Step 3: Add error handling and retry logic**

Add these to `anthropic_provider.py` (before the `AnthropicProvider` class):

```python
# ---------------------------------------------------------------------------
# Provider error types
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Error from an LLM provider, with retryability info."""

    def __init__(
        self,
        message: str = "",
        *,
        retryable: bool = False,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after = retry_after


def _translate_anthropic_error(error: Exception) -> dict[str, Any]:
    """Translate an Anthropic SDK exception into a structured error dict.

    Returns:
        Dict with keys: message, retryable, status_code, retry_after
    """
    import anthropic

    status_code = getattr(error, "status_code", None)
    if hasattr(error, "response"):
        status_code = status_code or getattr(error.response, "status_code", None)

    retry_after = None
    if hasattr(error, "response") and error.response is not None:
        headers = getattr(error.response, "headers", {})
        ra = headers.get("retry-after")
        if ra:
            try:
                retry_after = float(ra)
            except (ValueError, TypeError):
                pass

    if isinstance(error, anthropic.RateLimitError):
        return {
            "message": str(error),
            "retryable": True,
            "status_code": status_code or 429,
            "retry_after": retry_after,
        }
    elif isinstance(error, anthropic.AuthenticationError):
        return {
            "message": str(error),
            "retryable": False,
            "status_code": status_code or 401,
            "retry_after": None,
        }
    elif isinstance(error, anthropic.BadRequestError):
        return {
            "message": str(error),
            "retryable": False,
            "status_code": status_code or 400,
            "retry_after": None,
        }
    elif isinstance(error, anthropic.APIStatusError):
        sc = status_code or 500
        return {
            "message": str(error),
            "retryable": sc >= 500 or sc == 529,
            "status_code": sc,
            "retry_after": retry_after,
        }
    else:
        return {
            "message": str(error),
            "retryable": True,
            "status_code": None,
            "retry_after": None,
        }


# ---------------------------------------------------------------------------
# Retry with backoff
# ---------------------------------------------------------------------------

import asyncio
import random


async def retry_with_backoff(
    fn,
    max_retries: int = 5,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
) -> Any:
    """Retry an async function with exponential backoff.

    Args:
        fn: Async callable to retry
        max_retries: Maximum number of retries (0 = no retries)
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        jitter: Whether to add random jitter

    Returns:
        Result of fn()

    Raises:
        ProviderError: If all retries exhausted or error is non-retryable
    """
    last_error: Exception | None = None
    delay = initial_delay

    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except ProviderError as e:
            last_error = e
            if not e.retryable or attempt == max_retries:
                raise
            # Use retry_after from error if available
            wait = e.retry_after if e.retry_after else delay
            if jitter:
                wait = wait * (0.5 + random.random())
            wait = min(wait, max_delay)
            logger.info(
                "Retry %d/%d after %.1fs: %s",
                attempt + 1,
                max_retries,
                wait,
                str(e)[:100],
            )
            await asyncio.sleep(wait)
            delay = min(delay * 2, max_delay)
        except Exception as e:
            last_error = e
            if attempt == max_retries:
                raise
            wait = delay
            if jitter:
                wait = wait * (0.5 + random.random())
            wait = min(wait, max_delay)
            await asyncio.sleep(wait)
            delay = min(delay * 2, max_delay)

    raise last_error  # type: ignore[misc]
```

Also update the imports at the top of the file — add `random` alongside `asyncio`.

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_anthropic_provider.py::TestErrorTranslation tests/test_anthropic_provider.py::TestRetryWithBackoff -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/src/amplifier_providers/providers/anthropic_provider.py services/amplifier-providers/tests/test_anthropic_provider.py && git commit -m "feat(anthropic): port error translation and retry_with_backoff logic"
```

---

### Task 4: Port `complete()` method with tool-result repair

**Files:**
- Modify: `services/amplifier-providers/src/amplifier_providers/providers/anthropic_provider.py`
- Modify: `services/amplifier-providers/tests/test_anthropic_provider.py`

This is the main entry point. It orchestrates: tool-result repair → message separation → system block construction → API call with retry → response conversion.

**Step 1: Write the failing tests**

Append to `services/amplifier-providers/tests/test_anthropic_provider.py`:

```python
# ---------------------------------------------------------------------------
# complete() method tests (with mocked Anthropic client)
# ---------------------------------------------------------------------------
from unittest.mock import AsyncMock, MagicMock, patch


class TestComplete:
    """Tests for the complete() method with mocked Anthropic client."""

    def _make_provider(self) -> Any:
        from amplifier_providers.providers.anthropic_provider import AnthropicProvider

        p = AnthropicProvider(config={"api_key": "test-key"})
        return p

    def _mock_anthropic_response(
        self,
        text: str = "Hello!",
        *,
        tool_use: dict | None = None,
        input_tokens: int = 50,
        output_tokens: int = 25,
    ) -> MagicMock:
        """Build a mock Anthropic response object."""
        content = []

        class TextBlock:
            type = "text"

            def __init__(self, t):
                self.text = t

        class ToolUseBlock:
            type = "tool_use"

            def __init__(self, d):
                self.id = d["id"]
                self.name = d["name"]
                self.input = d["input"]

        if text:
            content.append(TextBlock(text))
        if tool_use:
            content.append(ToolUseBlock(tool_use))

        mock_usage = MagicMock()
        mock_usage.input_tokens = input_tokens
        mock_usage.output_tokens = output_tokens
        mock_usage.cache_creation_input_tokens = 0
        mock_usage.cache_read_input_tokens = 0

        mock_response = MagicMock()
        mock_response.id = "msg_test456"
        mock_response.content = content
        mock_response.model = "claude-sonnet-4-20250514"
        mock_response.stop_reason = "tool_use" if tool_use else "end_turn"
        mock_response.usage = mock_usage
        mock_response.type = "message"
        return mock_response

    async def test_complete_returns_chat_response(self) -> None:
        """complete() returns a ChatResponse with text content."""
        p = self._make_provider()
        mock_response = self._mock_anthropic_response("Hello from Claude!")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        p._client = mock_client

        request = ChatRequest(
            messages=[Message(role="user", content="Hello")],
            system="You are helpful.",
        )
        response = await p.complete(request)

        assert isinstance(response, ChatResponse)
        assert response.content is not None
        assert len(response.content) >= 1
        assert response.content[0].text == "Hello from Claude!"

    async def test_complete_with_tools(self) -> None:
        """complete() passes tools to Anthropic and returns tool calls."""
        p = self._make_provider()
        mock_response = self._mock_anthropic_response(
            "I'll read that.",
            tool_use={"id": "toolu_abc", "name": "read_file", "input": {"path": "x.txt"}},
        )

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        p._client = mock_client

        request = ChatRequest(
            messages=[Message(role="user", content="Read x.txt")],
            tools=[
                ToolSpec(
                    name="read_file",
                    description="Read a file",
                    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
                )
            ],
        )
        response = await p.complete(request)

        assert response.tool_calls is not None
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "read_file"

        # Verify tools were passed to the Anthropic client
        call_kwargs = mock_client.messages.create.call_args
        assert "tools" in call_kwargs.kwargs

    async def test_complete_system_passed_as_system_param(self) -> None:
        """System message is passed via the system parameter, not in messages."""
        p = self._make_provider()
        mock_response = self._mock_anthropic_response("OK")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        p._client = mock_client

        request = ChatRequest(
            messages=[
                Message(role="system", content="Be helpful"),
                Message(role="user", content="Hello"),
            ],
        )
        await p.complete(request)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        # System should be in the system parameter
        assert "system" in call_kwargs
        # Messages should NOT contain system messages
        api_messages = call_kwargs["messages"]
        for m in api_messages:
            assert m["role"] != "system"

    async def test_complete_usage_populated(self) -> None:
        """complete() populates Usage with correct token counts."""
        p = self._make_provider()
        mock_response = self._mock_anthropic_response(
            "done", input_tokens=200, output_tokens=100
        )

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        p._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="count")])
        response = await p.complete(request)

        assert response.usage is not None
        assert response.usage.input_tokens == 200
        assert response.usage.output_tokens == 100
        assert response.usage.total_tokens == 300


# ---------------------------------------------------------------------------
# Tool-result repair tests
# ---------------------------------------------------------------------------


class TestToolResultRepair:
    """Tests for tool-result repair logic in complete()."""

    def _make_provider(self) -> Any:
        from amplifier_providers.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(config={"api_key": "test-key"})

    def test_find_missing_tool_results(self) -> None:
        """Detect tool calls without matching tool result messages."""
        p = self._make_provider()
        messages = [
            Message(role="user", content="Do something"),
            Message(
                role="assistant",
                content=[ToolCallBlock(id="tc_1", name="bash", input={"command": "ls"})],
            ),
            # Missing tool result for tc_1
            Message(role="user", content="What happened?"),
        ]
        missing = p._find_missing_tool_results(messages)
        assert len(missing) == 1
        assert missing[0][1] == "tc_1"  # (msg_idx, call_id, name, args)

    def test_no_missing_when_result_present(self) -> None:
        """No missing results when all tool calls have matching tool results."""
        p = self._make_provider()
        messages = [
            Message(
                role="assistant",
                content=[ToolCallBlock(id="tc_1", name="bash", input={"command": "ls"})],
            ),
            Message(role="tool", content="file1.txt", tool_call_id="tc_1", name="bash"),
        ]
        missing = p._find_missing_tool_results(messages)
        assert len(missing) == 0

    def test_repaired_ids_not_detected_again(self) -> None:
        """Tool IDs already repaired are excluded from missing detection."""
        p = self._make_provider()
        p._repaired_tool_ids.add("tc_1")
        messages = [
            Message(
                role="assistant",
                content=[ToolCallBlock(id="tc_1", name="bash", input={"command": "ls"})],
            ),
            # No tool result for tc_1, but it's already in _repaired_tool_ids
        ]
        missing = p._find_missing_tool_results(messages)
        assert len(missing) == 0
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_anthropic_provider.py::TestComplete -v
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_anthropic_provider.py::TestToolResultRepair -v
```

Expected: FAIL — `complete()` still raises `NotImplementedError`, `_find_missing_tool_results` doesn't exist.

**Step 3: Implement `complete()`, `_find_missing_tool_results`, and `_create_synthetic_result`**

Replace the placeholder `complete()` method in `AnthropicProvider` with:

```python
    # ------------------------------------------------------------------
    # Tool-result repair
    # ------------------------------------------------------------------

    def _find_missing_tool_results(
        self, messages: list[Message]
    ) -> list[tuple[int, str, str, dict]]:
        """Find tool calls without matching results.

        Returns:
            List of (msg_idx, call_id, tool_name, tool_input) tuples
        """
        tool_calls_seen: dict[str, tuple[int, str, dict]] = {}
        tool_results_seen: set[str] = set()

        for idx, msg in enumerate(messages):
            if msg.role == "assistant" and isinstance(msg.content, list):
                for block in msg.content:
                    if hasattr(block, "type") and block.type == "tool_call":
                        tc_id = getattr(block, "id", "")
                        tc_name = getattr(block, "name", "")
                        tc_input = getattr(block, "input", {})
                        if tc_id:
                            tool_calls_seen[tc_id] = (idx, tc_name, tc_input)
            elif msg.role == "tool" and msg.tool_call_id:
                tool_results_seen.add(msg.tool_call_id)

        return [
            (msg_idx, call_id, name, args)
            for call_id, (msg_idx, name, args) in tool_calls_seen.items()
            if call_id not in tool_results_seen
            and call_id not in self._repaired_tool_ids
        ]

    def _create_synthetic_result(self, call_id: str, tool_name: str) -> Message:
        """Create synthetic error result for a missing tool response."""
        return Message(
            role="tool",
            content=(
                f"[SYSTEM ERROR: Tool result missing from conversation history]\n\n"
                f"Tool: {tool_name}\n"
                f"Call ID: {call_id}\n\n"
                f"This indicates the tool result was lost after execution.\n"
                f"Please acknowledge this error and offer to retry the operation."
            ),
            tool_call_id=call_id,
            name=tool_name,
        )

    # ------------------------------------------------------------------
    # Main completion method
    # ------------------------------------------------------------------

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Generate completion using Anthropic Messages API.

        Args:
            request: ChatRequest with messages, tools, system
            **kwargs: Provider-specific overrides (model, max_tokens, etc.)

        Returns:
            ChatResponse with content blocks, tool calls, usage
        """
        # REPAIR: Check for missing tool results
        missing = self._find_missing_tool_results(request.messages)
        if missing:
            logger.warning(
                "Detected %d missing tool result(s), injecting synthetic errors: %s",
                len(missing),
                [cid for _, cid, _, _ in missing],
            )
            for msg_idx, call_id, tool_name, _ in sorted(
                missing, key=lambda x: x[0], reverse=True
            ):
                synthetic = self._create_synthetic_result(call_id, tool_name)
                request.messages.insert(msg_idx + 1, synthetic)
                self._repaired_tool_ids.add(call_id)

        # Separate messages by role
        message_list = list(request.messages)
        system_msgs = [m for m in message_list if m.role == "system"]
        conversation = [m for m in message_list if m.role != "system"]

        # Build system parameter with cache_control for prompt caching
        system_param = None
        if request.system:
            system_param = [
                {
                    "type": "text",
                    "text": request.system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        elif system_msgs:
            system_blocks = []
            for sm in system_msgs:
                text = sm.content if isinstance(sm.content, str) else ""
                if text:
                    system_blocks.append(
                        {
                            "type": "text",
                            "text": text,
                            "cache_control": {"type": "ephemeral"},
                        }
                    )
            if system_blocks:
                system_param = system_blocks

        # Convert messages
        api_messages = self._convert_messages(conversation)

        # Build API params
        params: dict[str, Any] = {
            "model": kwargs.get("model", self.default_model),
            "messages": api_messages,
            "max_tokens": request.max_output_tokens or kwargs.get(
                "max_tokens", self.max_tokens
            ),
        }

        if system_param:
            params["system"] = system_param

        if request.temperature is not None:
            params["temperature"] = request.temperature
        elif self.temperature is not None:
            params["temperature"] = self.temperature

        # Add tools if provided
        if request.tools:
            params["tools"] = self._convert_tools_from_request(request.tools)

        # Extended thinking
        thinking_budget = kwargs.get("thinking_budget", self.thinking_budget)
        if thinking_budget:
            params["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_budget,
            }
            # Ensure max_tokens is large enough for thinking
            buffer = kwargs.get("thinking_budget_buffer", 1024)
            params["max_tokens"] = max(
                params["max_tokens"], thinking_budget + buffer
            )

        logger.info(
            "Anthropic API call: model=%s, messages=%d, tools=%d",
            params["model"],
            len(api_messages),
            len(params.get("tools", [])),
        )

        # Pre-emptive rate limit throttle
        await self._rate_limit_state.maybe_throttle()

        # API call with retry
        async def _do_complete():
            try:
                return await self.client.messages.create(**params)
            except Exception as e:
                error_info = _translate_anthropic_error(e)
                raise ProviderError(
                    error_info["message"],
                    retryable=error_info["retryable"],
                    status_code=error_info["status_code"],
                    retry_after=error_info["retry_after"],
                ) from e

        response = await retry_with_backoff(
            _do_complete,
            max_retries=int(self.config.get("max_retries", 5)),
            initial_delay=float(self.config.get("min_retry_delay", 1.0)),
            max_delay=float(self.config.get("max_retry_delay", 60.0)),
        )

        # Update rate limit state from response headers
        # (Anthropic returns these on the response object for some SDK versions)
        self._rate_limit_state.update_from_response(response)

        # Convert response
        return self._convert_to_chat_response(response)
```

Also update `_RateLimitState` to add `maybe_throttle` and `update_from_response`:

```python
class _RateLimitState:
    """Tracks Anthropic rate limit headers for pre-emptive throttling."""

    def __init__(self) -> None:
        self.requests_limit: int | None = None
        self.requests_remaining: int | None = None
        self.tokens_limit: int | None = None
        self.tokens_remaining: int | None = None
        self.retry_after: float | None = None

    async def maybe_throttle(self) -> None:
        """Pre-emptively delay if close to rate limits."""
        if self.retry_after and self.retry_after > 0:
            wait = min(self.retry_after, 60.0)
            logger.info("Pre-emptive rate limit throttle: %.1fs", wait)
            await asyncio.sleep(wait)
            self.retry_after = None

    def update_from_response(self, response: Any) -> None:
        """Extract rate limit info from Anthropic response headers if available."""
        # The Anthropic SDK exposes rate limit headers on some response types
        headers = getattr(response, "_headers", None) or getattr(
            response, "headers", None
        )
        if not headers:
            return

        def get_int(key: str) -> int | None:
            val = headers.get(key)
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    pass
            return None

        self.requests_limit = get_int("anthropic-ratelimit-requests-limit")
        self.requests_remaining = get_int("anthropic-ratelimit-requests-remaining")
        self.tokens_limit = get_int("anthropic-ratelimit-tokens-limit")
        self.tokens_remaining = get_int("anthropic-ratelimit-tokens-remaining")

        ra = headers.get("retry-after")
        if ra:
            try:
                self.retry_after = float(ra)
            except (ValueError, TypeError):
                pass
```

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_anthropic_provider.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/src/amplifier_providers/providers/anthropic_provider.py services/amplifier-providers/tests/test_anthropic_provider.py && git commit -m "feat(anthropic): port complete() with tool-result repair, system/prompt caching, retry"
```

---

### Task 5: Port rate limiting with pre-emptive throttle tests

**Files:**
- Modify: `services/amplifier-providers/tests/test_anthropic_provider.py`

The `_RateLimitState` class and `maybe_throttle` were added in Task 4. This task adds focused tests.

**Step 1: Write the tests**

Append to `services/amplifier-providers/tests/test_anthropic_provider.py`:

```python
# ---------------------------------------------------------------------------
# Rate limit state tests
# ---------------------------------------------------------------------------


class TestRateLimitState:
    """Tests for _RateLimitState pre-emptive throttling."""

    async def test_no_throttle_when_no_retry_after(self) -> None:
        """No delay when retry_after is not set."""
        from amplifier_providers.providers.anthropic_provider import _RateLimitState
        import time

        state = _RateLimitState()
        start = time.monotonic()
        await state.maybe_throttle()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # Should be essentially instant

    async def test_throttle_when_retry_after_set(self) -> None:
        """Delays when retry_after is set, then clears it."""
        from amplifier_providers.providers.anthropic_provider import _RateLimitState
        import time

        state = _RateLimitState()
        state.retry_after = 0.1  # 100ms
        start = time.monotonic()
        await state.maybe_throttle()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.08  # Should have waited ~100ms
        assert state.retry_after is None  # Cleared after throttle

    def test_update_from_response_with_headers(self) -> None:
        """Rate limit state updates from response headers."""
        from amplifier_providers.providers.anthropic_provider import _RateLimitState

        state = _RateLimitState()

        class MockResponse:
            headers = {
                "anthropic-ratelimit-requests-limit": "100",
                "anthropic-ratelimit-requests-remaining": "50",
                "anthropic-ratelimit-tokens-limit": "100000",
                "anthropic-ratelimit-tokens-remaining": "80000",
            }

        state.update_from_response(MockResponse())
        assert state.requests_limit == 100
        assert state.requests_remaining == 50
        assert state.tokens_limit == 100000
        assert state.tokens_remaining == 80000

    def test_update_from_response_without_headers(self) -> None:
        """Rate limit state handles responses without headers gracefully."""
        from amplifier_providers.providers.anthropic_provider import _RateLimitState

        state = _RateLimitState()
        state.update_from_response(MagicMock(spec=[]))  # No headers attribute
        # Should not crash; state remains at defaults
        assert state.requests_limit is None
```

**Step 2: Run tests**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_anthropic_provider.py::TestRateLimitState -v
```

Expected: All PASS (implementation already in place from Task 4).

**Step 3: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/tests/test_anthropic_provider.py && git commit -m "test(anthropic): add rate limit state throttle tests"
```

---

### Task 6: Port extended thinking support tests

**Files:**
- Modify: `services/amplifier-providers/tests/test_anthropic_provider.py`

Extended thinking was wired in Task 4 (`thinking_budget` config). This task adds focused tests.

**Step 1: Write the tests**

Append to `services/amplifier-providers/tests/test_anthropic_provider.py`:

```python
# ---------------------------------------------------------------------------
# Extended thinking tests
# ---------------------------------------------------------------------------


class TestExtendedThinking:
    """Tests for extended thinking parameter handling."""

    def _make_provider(self, **config_overrides) -> Any:
        from amplifier_providers.providers.anthropic_provider import AnthropicProvider

        config = {"api_key": "test-key"}
        config.update(config_overrides)
        return AnthropicProvider(config=config)

    async def test_thinking_budget_from_config(self) -> None:
        """thinking_budget in config adds thinking parameter to API call."""
        p = self._make_provider(thinking_budget=10000)

        mock_response = MagicMock()
        mock_response.content = [type("B", (), {"type": "text", "text": "answer"})()]
        mock_response.model = "claude-sonnet-4-20250514"
        mock_response.stop_reason = "end_turn"
        mock_response.usage = MagicMock(
            input_tokens=50, output_tokens=25,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        mock_response.id = "msg_x"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        p._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Think hard")])
        await p.complete(request)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "thinking" in call_kwargs
        assert call_kwargs["thinking"]["type"] == "enabled"
        assert call_kwargs["thinking"]["budget_tokens"] == 10000

    async def test_thinking_budget_from_kwargs(self) -> None:
        """thinking_budget in kwargs overrides config."""
        p = self._make_provider()

        mock_response = MagicMock()
        mock_response.content = [type("B", (), {"type": "text", "text": "answer"})()]
        mock_response.model = "claude-sonnet-4-20250514"
        mock_response.stop_reason = "end_turn"
        mock_response.usage = MagicMock(
            input_tokens=50, output_tokens=25,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        mock_response.id = "msg_x"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        p._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Think")])
        await p.complete(request, thinking_budget=5000)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["thinking"]["budget_tokens"] == 5000

    async def test_no_thinking_when_budget_not_set(self) -> None:
        """No thinking parameter when budget is not set."""
        p = self._make_provider()

        mock_response = MagicMock()
        mock_response.content = [type("B", (), {"type": "text", "text": "answer"})()]
        mock_response.model = "claude-sonnet-4-20250514"
        mock_response.stop_reason = "end_turn"
        mock_response.usage = MagicMock(
            input_tokens=50, output_tokens=25,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        mock_response.id = "msg_x"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        p._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Hi")])
        await p.complete(request)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "thinking" not in call_kwargs

    def test_thinking_block_in_response(self) -> None:
        """ThinkingBlock in Anthropic response appears in ChatResponse."""
        p = self._make_provider()
        # Reuse the mock response helper approach
        mock_content = [
            type("B", (), {"type": "thinking", "thinking": "Step 1: analyze...", "signature": "sig_1"})(),
            type("B", (), {"type": "text", "text": "Here's my answer."})(),
        ]
        mock_usage = MagicMock(
            input_tokens=100, output_tokens=200,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        mock_response = MagicMock(
            id="msg_y", content=mock_content, model="claude-sonnet-4-20250514",
            stop_reason="end_turn", usage=mock_usage,
        )

        result = p._convert_to_chat_response(mock_response)
        assert len(result.content) == 2
        assert result.content[0].type == "thinking"
        assert result.content[0].thinking == "Step 1: analyze..."
        assert result.content[0].signature == "sig_1"
        assert result.content[1].type == "text"
        assert result.content[1].text == "Here's my answer."
```

**Step 2: Run tests**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_anthropic_provider.py::TestExtendedThinking -v
```

Expected: All PASS.

**Step 3: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/tests/test_anthropic_provider.py && git commit -m "test(anthropic): add extended thinking tests"
```

---

### Task 7: Update test_describe.py and add README.md

**Files:**
- Modify: `services/amplifier-providers/tests/test_describe.py`
- Create: `services/amplifier-providers/README.md`

**Step 1: Update `test_describe.py` to account for non-stub Anthropic**

The existing `test_stub_providers_raise_not_implemented` test (line 88) asserts that all 7 non-mock providers raise `NotImplementedError`. Now that Anthropic is implemented, remove it from the stub list.

In `services/amplifier-providers/tests/test_describe.py`, change the `stub_imports` list in `test_stub_providers_raise_not_implemented` to remove the Anthropic entry:

```python
def test_stub_providers_raise_not_implemented() -> None:
    """All 6 stub providers must raise NotImplementedError on complete()."""
    stub_imports = [
        ("amplifier_providers.providers.openai_provider", "OpenAIProvider"),
        ("amplifier_providers.providers.azure_openai_provider", "AzureOpenAIProvider"),
        ("amplifier_providers.providers.gemini_provider", "GeminiProvider"),
        ("amplifier_providers.providers.ollama_provider", "OllamaProvider"),
        ("amplifier_providers.providers.vllm_provider", "VllmProvider"),
        (
            "amplifier_providers.providers.github_copilot_provider",
            "GitHubCopilotProvider",
        ),
    ]
    # ... rest of function unchanged
```

Also update the docstring from "All 7 stub providers" to "All 6 stub providers".

**Step 2: Run all existing tests to verify no regressions**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/ -v
```

Expected: All PASS. The discover/describe tests still find all 8 providers. The stub test now only checks 6.

**Step 3: Create `services/amplifier-providers/README.md`**

```markdown
# amplifier-providers

LLM provider adapters for Amplifier IPC.

## Implemented Providers

| Provider | Status | SDK |
|---|---|---|
| `mock` | ✅ Complete | None (canned responses) |
| `anthropic` | ✅ Complete | `anthropic` |
| `openai` | Stub | `openai` |
| `azure_openai` | Stub | `openai` + `azure-identity` |
| `gemini` | Stub | `google-generativeai` |
| `ollama` | Stub | `ollama` |
| `vllm` | Stub | `openai` |
| `github_copilot` | Stub | `openai` |

## Anthropic Provider

### Configuration

The Anthropic provider accepts a `config` dict with these keys:

| Key | Type | Default | Description |
|---|---|---|---|
| `api_key` | `str` | `$ANTHROPIC_API_KEY` | API key (config takes precedence over env var) |
| `model` | `str` | `claude-sonnet-4-20250514` | Default model |
| `max_tokens` | `int` | `16384` | Default max output tokens |
| `temperature` | `float` | `None` | Temperature (None = not sent) |
| `thinking_budget` | `int` | `None` | Extended thinking budget in tokens |
| `max_retries` | `int` | `5` | Max retry attempts |
| `min_retry_delay` | `float` | `1.0` | Initial retry delay (seconds) |
| `max_retry_delay` | `float` | `60.0` | Max retry delay (seconds) |

### Features

- **Message conversion** — Converts between Amplifier's Message/TextBlock/ThinkingBlock/ToolCallBlock and Anthropic's Messages API format
- **Tool conversion** — ToolSpec → Anthropic tool format with input_schema
- **Error translation** — Anthropic SDK errors → ProviderError with retryability info
- **Retry with backoff** — Exponential backoff with jitter, respects retry-after headers
- **Rate limit tracking** — Pre-emptive throttle based on Anthropic rate limit headers
- **Prompt caching** — cache_control on system blocks for reduced latency
- **Extended thinking** — thinking_budget parameter enables Claude's extended thinking
- **Tool-result repair** — Detects missing tool results and injects synthetic error messages

### Dropped from Upstream

These methods exist in the upstream `amplifier-module-provider-anthropic` but are not part of the IPC protocol:

| Method | Reason |
|---|---|
| `get_info()` | Provider metadata — not in IPC wire protocol yet |
| `list_models()` | Model discovery — not in IPC wire protocol yet |
| `close()` | Client cleanup — IPC services are process-per-turn |
| `mount()` | v1 lifecycle — replaced by `@provider` decorator |

### Streaming

Provider streaming (`stream.provider.*` notifications) is designed in the IPC protocol spec but not implemented in the Anthropic provider yet. The `complete()` method returns the full `ChatResponse` synchronously. Streaming support will be added when the orchestrator implements the streaming notification relay.

## Installation

```bash
# With anthropic support
pip install amplifier-providers[anthropic]

# All providers
pip install amplifier-providers[all]
```

## Running as IPC Service

```bash
amplifier-providers-serve
```

Or:

```bash
python -m amplifier_providers
```
```

**Step 4: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/tests/test_describe.py services/amplifier-providers/README.md && git commit -m "docs(anthropic): update stub test for 6 remaining stubs, add README.md"
```

---

### Task 8: Integration test through IPC Server path

**Files:**
- Create: `services/amplifier-providers/tests/test_anthropic_integration.py`

This tests the full provider through the JSON-RPC server: `describe` sees anthropic, `provider.complete` routes correctly, ChatResponse comes back.

**Step 1: Write the integration test**

Create `services/amplifier-providers/tests/test_anthropic_integration.py`:

```python
"""Integration test: Anthropic provider through the IPC Server path.

Tests that:
1. describe reports anthropic as a real provider (not stub)
2. provider.complete routes to AnthropicProvider.complete()
3. ChatResponse comes back correctly through JSON-RPC
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_ipc_protocol import ChatRequest, ChatResponse, Message, ToolSpec
from amplifier_ipc_protocol.server import Server


async def test_describe_reports_anthropic_provider() -> None:
    """Server.describe reports anthropic with correct name."""
    server = Server("amplifier_providers")
    result = await server._handle_describe()

    providers = result["capabilities"]["providers"]
    anthropic_entry = next(
        (p for p in providers if p.get("name") == "anthropic"), None
    )
    assert anthropic_entry is not None, (
        f"anthropic not in describe providers: {[p.get('name') for p in providers]}"
    )


async def test_provider_complete_routes_to_anthropic() -> None:
    """provider.complete with name=anthropic routes to AnthropicProvider."""
    server = Server("amplifier_providers")

    # The server discovers providers via scan_package. Find the anthropic one.
    anthropic_provider = None
    for p in server._providers:
        if getattr(p, "name", None) == "anthropic":
            anthropic_provider = p
            break
    assert anthropic_provider is not None, "AnthropicProvider not discovered by server"

    # Mock the Anthropic client on the provider instance
    mock_content = [
        type("B", (), {"type": "text", "text": "Integration test response"})()
    ]
    mock_usage = MagicMock(
        input_tokens=10, output_tokens=5,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
    )
    mock_response = MagicMock(
        id="msg_integration",
        content=mock_content,
        model="claude-sonnet-4-20250514",
        stop_reason="end_turn",
        usage=mock_usage,
    )

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    anthropic_provider._client = mock_client

    # Construct the JSON-RPC params as the host would send them
    request_data = ChatRequest(
        messages=[Message(role="user", content="Hello from integration test")],
    ).model_dump(mode="json")

    # Call through the server's provider.complete handler
    result = await server._handle_provider_complete(
        {"name": "anthropic", "request": request_data}
    )

    # The result should be a ChatResponse dict
    assert "content" in result
    assert len(result["content"]) >= 1
    # Verify the text came through
    first_block = result["content"][0]
    assert first_block["text"] == "Integration test response"


async def test_provider_complete_returns_usage() -> None:
    """provider.complete returns usage info in the response."""
    server = Server("amplifier_providers")

    anthropic_provider = None
    for p in server._providers:
        if getattr(p, "name", None) == "anthropic":
            anthropic_provider = p
            break
    assert anthropic_provider is not None

    mock_content = [type("B", (), {"type": "text", "text": "hi"})()]
    mock_usage = MagicMock(
        input_tokens=100, output_tokens=50,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
    )
    mock_response = MagicMock(
        id="msg_usage", content=mock_content,
        model="claude-sonnet-4-20250514", stop_reason="end_turn",
        usage=mock_usage,
    )

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    anthropic_provider._client = mock_client

    request_data = ChatRequest(
        messages=[Message(role="user", content="usage test")],
    ).model_dump(mode="json")

    result = await server._handle_provider_complete(
        {"name": "anthropic", "request": request_data}
    )

    assert "usage" in result
    assert result["usage"]["input_tokens"] == 100
    assert result["usage"]["output_tokens"] == 50


async def test_provider_complete_with_tool_calls() -> None:
    """provider.complete returns tool_calls when Anthropic responds with tool_use."""
    server = Server("amplifier_providers")

    anthropic_provider = None
    for p in server._providers:
        if getattr(p, "name", None) == "anthropic":
            anthropic_provider = p
            break
    assert anthropic_provider is not None

    mock_content = [
        type("B", (), {"type": "text", "text": "I'll read that."})(),
        type("B", (), {
            "type": "tool_use", "id": "toolu_int", "name": "read_file",
            "input": {"path": "test.txt"},
        })(),
    ]
    mock_usage = MagicMock(
        input_tokens=20, output_tokens=10,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
    )
    mock_response = MagicMock(
        id="msg_tools", content=mock_content,
        model="claude-sonnet-4-20250514", stop_reason="tool_use",
        usage=mock_usage,
    )

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    anthropic_provider._client = mock_client

    request_data = ChatRequest(
        messages=[Message(role="user", content="Read test.txt")],
        tools=[ToolSpec(
            name="read_file", description="Read a file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        )],
    ).model_dump(mode="json")

    result = await server._handle_provider_complete(
        {"name": "anthropic", "request": request_data}
    )

    assert "tool_calls" in result
    assert result["tool_calls"] is not None
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["tool"] == "read_file"
```

**Step 2: Run integration tests**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_anthropic_integration.py -v
```

Expected: All PASS. If `_handle_provider_complete` doesn't exist on the Server, check the Server implementation — it may dispatch `provider.complete` differently. Adapt the test to match the actual server dispatch pattern. The key verification is: request goes in via the server's handler, ChatResponse comes out with correct content.

**Step 3: Run full test suite**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/ -v
```

Expected: All tests PASS across all test files.

**Step 4: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/tests/test_anthropic_integration.py && git commit -m "test(anthropic): add integration tests through IPC Server path"
```

---

## Summary

| Task | What | Tests |
|---|---|---|
| 1 | `_convert_messages()`, `_convert_assistant_content()` | 7 tests |
| 2 | `_convert_tools_from_request()`, `_convert_to_chat_response()` | 9 tests |
| 3 | `ProviderError`, `_translate_anthropic_error()`, `retry_with_backoff()` | 7 tests |
| 4 | `complete()`, `_find_missing_tool_results()`, `_create_synthetic_result()` | 8 tests |
| 5 | `_RateLimitState` throttle tests | 4 tests |
| 6 | Extended thinking tests | 4 tests |
| 7 | Update test_describe.py, create README.md | 0 new tests (fix 1 existing) |
| 8 | Integration test through IPC Server | 4 tests |
| **Total** | | **~43 tests** |

After Phase 2, the `amplifier-providers` service has a fully functional Anthropic provider that can make real API calls (when given a valid API key) through the IPC Server path. Phase 3 will use this as the template for the remaining 6 providers.
