"""Tests for AnthropicProvider._convert_messages() and related methods."""

from __future__ import annotations

import anthropic
import httpx
import pytest

from amplifier_ipc_protocol import ChatRequest, ChatResponse, Message
from amplifier_ipc_protocol.models import (
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolSpec,
)

from amplifier_providers.providers.anthropic_provider import (
    AnthropicProvider,
    ProviderError,
    _RateLimitState,
    _translate_anthropic_error,
    retry_with_backoff,
)


# ---------------------------------------------------------------------------
# Mock helpers for _convert_to_chat_response tests
# ---------------------------------------------------------------------------


class MockUsage:
    """Simulates an Anthropic API usage object."""

    def __init__(
        self,
        input_tokens: int = 100,
        output_tokens: int = 50,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class MockTextBlock:
    """Simulates an Anthropic text content block."""

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class MockThinkingBlock:
    """Simulates an Anthropic thinking content block."""

    def __init__(self, thinking: str, signature: str | None = None) -> None:
        self.type = "thinking"
        self.thinking = thinking
        self.signature = signature


class MockToolUseBlock:
    """Simulates an Anthropic tool_use content block."""

    def __init__(self, tool_id: str, name: str, input: dict) -> None:  # noqa: A002
        self.type = "tool_use"
        self.id = tool_id
        self.name = name
        self.input = input


class MockResponse:
    """Simulates an Anthropic Messages API response object."""

    def __init__(
        self,
        content: list,
        stop_reason: str = "end_turn",
        usage: MockUsage | None = None,
        model: str = "claude-test-model",
    ) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage or MockUsage()
        self.model = model


def _make_anthropic_response(
    content: list,
    stop_reason: str = "end_turn",
    **usage_kwargs,
) -> MockResponse:
    """Helper to create a MockResponse with optional usage overrides."""
    return MockResponse(
        content=content,
        stop_reason=stop_reason,
        usage=MockUsage(**usage_kwargs),
    )


class TestConvertMessages:
    """Tests for AnthropicProvider._convert_messages()."""

    def setup_method(self) -> None:
        """Create a provider instance for each test (no API key needed)."""
        self.provider = AnthropicProvider(config={})

    def test_simple_user_message(self) -> None:
        """A single user message with string content converts to Anthropic format."""
        messages = [Message(role="user", content="Hello, Claude!")]
        result = self.provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello, Claude!"

    def test_user_assistant_alternation(self) -> None:
        """User and assistant messages convert directly preserving roles."""
        messages = [
            Message(role="user", content="What is 2+2?"),
            Message(role="assistant", content="The answer is 4."),
            Message(role="user", content="Thanks!"),
        ]
        result = self.provider._convert_messages(messages)

        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "What is 2+2?"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "user"
        assert result[2]["content"] == "Thanks!"

    def test_system_messages_excluded(self) -> None:
        """System messages are NOT included in the converted output."""
        messages = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
        ]
        result = self.provider._convert_messages(messages)

        roles = [m["role"] for m in result]
        assert "system" not in roles
        assert len(result) == 2  # only user + assistant

    def test_tool_result_message(self) -> None:
        """Tool result converts to user message with tool_result block.

        tool_use_id in the block must match the tool_call_id from the source message.
        """
        tool_call_id = "call_abc123"
        messages = [
            Message(
                role="tool",
                content="The file contents are: hello world",
                tool_call_id=tool_call_id,
            )
        ]
        result = self.provider._convert_messages(messages)

        assert len(result) == 1
        msg = result[0]
        assert msg["role"] == "user"
        assert isinstance(msg["content"], list)
        assert len(msg["content"]) == 1
        block = msg["content"][0]
        assert block["type"] == "tool_result"
        assert block["tool_use_id"] == tool_call_id

    def test_assistant_with_tool_calls(self) -> None:
        """Assistant message with ToolCallBlock content produces tool_use blocks."""
        tool_block = ToolCallBlock(
            id="call_xyz789",
            name="read_file",
            input={"path": "/tmp/test.txt"},
        )
        messages = [Message(role="assistant", content=[tool_block])]
        result = self.provider._convert_messages(messages)

        assert len(result) == 1
        msg = result[0]
        assert msg["role"] == "assistant"
        assert isinstance(msg["content"], list)

        tool_use_blocks = [b for b in msg["content"] if b.get("type") == "tool_use"]
        assert len(tool_use_blocks) == 1
        tool_use = tool_use_blocks[0]
        assert tool_use["id"] == "call_xyz789"
        assert tool_use["name"] == "read_file"
        assert tool_use["input"] == {"path": "/tmp/test.txt"}

    def test_developer_messages_become_xml_wrapped_user(self) -> None:
        """Developer role messages become XML-wrapped user messages with <context_file> tags."""
        file_content = "def hello():\n    print('world')"
        messages = [Message(role="developer", content=file_content)]
        result = self.provider._convert_messages(messages)

        assert len(result) == 1
        msg = result[0]
        assert msg["role"] == "user"
        content = msg["content"]
        assert "<context_file>" in content
        assert "</context_file>" in content
        assert file_content in content

    def test_thinking_block_in_assistant(self) -> None:
        """ThinkingBlock in assistant content is preserved with type='thinking' and signature."""
        thinking_block = ThinkingBlock(
            thinking="Let me think step by step...",
            signature="sig_abc123",
        )
        messages = [Message(role="assistant", content=[thinking_block])]
        result = self.provider._convert_messages(messages)

        assert len(result) == 1
        msg = result[0]
        assert msg["role"] == "assistant"
        assert isinstance(msg["content"], list)

        thinking_blocks = [b for b in msg["content"] if b.get("type") == "thinking"]
        assert len(thinking_blocks) == 1
        tb = thinking_blocks[0]
        assert tb["type"] == "thinking"
        assert tb["thinking"] == "Let me think step by step..."
        assert tb["signature"] == "sig_abc123"


class TestConvertToolsFromRequest:
    """Tests for AnthropicProvider._convert_tools_from_request()."""

    def setup_method(self) -> None:
        self.provider = AnthropicProvider(config={})

    def test_single_tool(self) -> None:
        """A single ToolSpec converts to Anthropic tool format with input_schema."""
        tools = [
            ToolSpec(
                name="read_file",
                description="Read the contents of a file",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            )
        ]
        result = self.provider._convert_tools_from_request(tools)

        assert len(result) == 1
        tool = result[0]
        assert tool["name"] == "read_file"
        assert tool["description"] == "Read the contents of a file"
        assert tool["input_schema"] == {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        }

    def test_multiple_tools(self) -> None:
        """Multiple tools all convert; names match the original specs."""
        tools = [
            ToolSpec(name="tool_a", description="First tool", parameters={}),
            ToolSpec(
                name="tool_b", description="Second tool", parameters={"type": "object"}
            ),
            ToolSpec(name="tool_c", description="Third tool", parameters={}),
        ]
        result = self.provider._convert_tools_from_request(tools)

        assert len(result) == 3
        names = [t["name"] for t in result]
        assert names == ["tool_a", "tool_b", "tool_c"]

    def test_empty_tools(self) -> None:
        """Empty tool list returns empty list."""
        result = self.provider._convert_tools_from_request([])
        assert result == []

    def test_tool_with_empty_parameters(self) -> None:
        """Tool with empty parameters dict produces valid empty input_schema."""
        tools = [
            ToolSpec(
                name="no_params_tool",
                description="A tool with no params",
                parameters={},
            )
        ]
        result = self.provider._convert_tools_from_request(tools)

        assert len(result) == 1
        assert result[0]["input_schema"] == {}


class TestConvertToChatResponse:
    """Tests for AnthropicProvider._convert_to_chat_response()."""

    def setup_method(self) -> None:
        self.provider = AnthropicProvider(config={})

    def test_text_response(self) -> None:
        """Text-only response produces ChatResponse with TextBlock; no tool_calls."""
        response = _make_anthropic_response(
            content=[MockTextBlock("Hello, world!")],
        )
        result = self.provider._convert_to_chat_response(response)

        assert result.tool_calls is None
        assert result.content_blocks is not None
        assert len(result.content_blocks) == 1
        block = result.content_blocks[0]
        assert isinstance(block, TextBlock)
        assert block.text == "Hello, world!"
        assert result.text == "Hello, world!"

    def test_tool_use_response(self) -> None:
        """Tool use block produces ToolCall in tool_calls and ToolCallBlock in content."""
        response = _make_anthropic_response(
            content=[
                MockTextBlock("I'll help you with that."),
                MockToolUseBlock(
                    tool_id="call_abc123",
                    name="read_file",
                    input={"path": "/tmp/test.txt"},
                ),
            ],
        )
        result = self.provider._convert_to_chat_response(response)

        # content_blocks has 2 items: TextBlock + ToolCallBlock
        assert result.content_blocks is not None
        assert len(result.content_blocks) == 2
        assert isinstance(result.content_blocks[0], TextBlock)
        assert isinstance(result.content_blocks[1], ToolCallBlock)

        # tool_calls list has 1 ToolCall
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.id == "call_abc123"
        assert tc.name == "read_file"
        assert tc.arguments == {"path": "/tmp/test.txt"}

    def test_thinking_response(self) -> None:
        """Thinking block produces ThinkingBlock with thinking text and signature."""
        response = _make_anthropic_response(
            content=[
                MockThinkingBlock(
                    thinking="Let me reason about this...",
                    signature="sig_xyz",
                ),
                MockTextBlock("The answer is 42."),
            ],
        )
        result = self.provider._convert_to_chat_response(response)

        assert result.content_blocks is not None
        thinking_blocks = [
            b for b in result.content_blocks if isinstance(b, ThinkingBlock)
        ]
        assert len(thinking_blocks) == 1
        tb = thinking_blocks[0]
        assert tb.thinking == "Let me reason about this..."
        assert tb.signature == "sig_xyz"

    def test_usage_extraction(self) -> None:
        """Usage tokens are correctly extracted: input, output, total, cache_read."""
        response = _make_anthropic_response(
            content=[MockTextBlock("Response text.")],
            input_tokens=200,
            output_tokens=100,
            cache_read_input_tokens=50,
            cache_creation_input_tokens=0,
        )
        result = self.provider._convert_to_chat_response(response)

        assert result.usage is not None
        assert result.usage.input_tokens == 200
        assert result.usage.output_tokens == 100
        assert result.usage.total_tokens == 300
        assert result.usage.cache_read_tokens == 50
        assert result.usage.cache_write_tokens is None  # 0 → None

    def test_finish_reason_mapping(self) -> None:
        """stop_reason from response maps to finish_reason in ChatResponse."""
        response = _make_anthropic_response(
            content=[MockTextBlock("Done.")],
            stop_reason="end_turn",
        )
        result = self.provider._convert_to_chat_response(response)

        assert result.finish_reason == "end_turn"

    def test_no_content_response(self) -> None:
        """Empty content list produces empty content_blocks, no tool_calls, text=None."""
        response = _make_anthropic_response(content=[])
        result = self.provider._convert_to_chat_response(response)

        assert result.content_blocks == []
        assert result.content == []
        assert result.tool_calls is None
        assert result.text is None


# ---------------------------------------------------------------------------
# Helper for creating mock Anthropic SDK errors
# ---------------------------------------------------------------------------


def _make_anthropic_request() -> httpx.Request:
    """Create a minimal httpx.Request for Anthropic error construction."""
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _make_httpx_response(
    status_code: int, headers: dict | None = None
) -> httpx.Response:
    """Create an httpx.Response with an attached request."""
    return httpx.Response(
        status_code,
        headers=headers or {},
        request=_make_anthropic_request(),
    )


# ---------------------------------------------------------------------------
# TestErrorTranslation
# ---------------------------------------------------------------------------


class TestErrorTranslation:
    """Tests for _translate_anthropic_error()."""

    def test_translate_rate_limit_error(self) -> None:
        """RateLimitError → retryable=True, status_code=429."""
        response = _make_httpx_response(429, headers={"retry-after": "5.0"})
        error = anthropic.RateLimitError("rate limited", response=response, body=None)

        result = _translate_anthropic_error(error)

        assert result["retryable"] is True
        assert result["status_code"] == 429

    def test_translate_auth_error(self) -> None:
        """AuthenticationError → retryable=False, status_code=401."""
        response = _make_httpx_response(401)
        error = anthropic.AuthenticationError(
            "unauthorized", response=response, body=None
        )

        result = _translate_anthropic_error(error)

        assert result["retryable"] is False
        assert result["status_code"] == 401

    def test_translate_bad_request_error(self) -> None:
        """BadRequestError → retryable=False, status_code=400."""
        response = _make_httpx_response(400)
        error = anthropic.BadRequestError("bad request", response=response, body=None)

        result = _translate_anthropic_error(error)

        assert result["retryable"] is False
        assert result["status_code"] == 400

    def test_translate_overloaded_error(self) -> None:
        """APIStatusError with status_code=529 → retryable=True, status_code=529."""
        response = _make_httpx_response(529)
        error = anthropic.APIStatusError("overloaded", response=response, body=None)

        result = _translate_anthropic_error(error)

        assert result["retryable"] is True
        assert result["status_code"] == 529


# ---------------------------------------------------------------------------
# TestRetryWithBackoff
# ---------------------------------------------------------------------------


class TestRetryWithBackoff:
    """Tests for retry_with_backoff()."""

    async def test_succeeds_first_try(self) -> None:
        """If the callable succeeds on first call, call_count=1."""
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_with_backoff(fn, max_retries=2, initial_delay=0.0)

        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_retryable_error(self) -> None:
        """Fails twice with retryable=True, succeeds on 3rd attempt → call_count=3."""
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ProviderError("temporary", retryable=True)
            return "ok"

        result = await retry_with_backoff(fn, max_retries=5, initial_delay=0.0)

        assert result == "ok"
        assert call_count == 3

    async def test_gives_up_after_max_retries(self) -> None:
        """Always fails with retryable=True → raises ProviderError after max_retries=2."""
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            raise ProviderError("always fails", retryable=True)

        with pytest.raises(ProviderError):
            await retry_with_backoff(fn, max_retries=2, initial_delay=0.0)

        # Initial attempt + 2 retries = 3 total calls
        assert call_count == 3

    async def test_non_retryable_error_not_retried(self) -> None:
        """retryable=False → raises immediately, call_count=1."""
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            raise ProviderError("fatal", retryable=False)

        with pytest.raises(ProviderError):
            await retry_with_backoff(fn, max_retries=5, initial_delay=0.0)

        assert call_count == 1


# ---------------------------------------------------------------------------
# TestComplete
# ---------------------------------------------------------------------------


class TestComplete:
    """Tests for AnthropicProvider.complete() — uses mocked Anthropic client."""

    def setup_method(self) -> None:
        """Create provider with a fake API key; real client is injected per test."""
        self.provider = AnthropicProvider(config={"api_key": "test-key"})

    async def test_complete_returns_chat_response(self) -> None:
        """complete() returns a ChatResponse with correct text content."""
        from unittest.mock import AsyncMock, MagicMock

        mock_response = _make_anthropic_response(
            content=[MockTextBlock("Hello from Claude!")],
        )
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        self.provider._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        result = await self.provider.complete(request)

        assert isinstance(result, ChatResponse)
        assert result.text == "Hello from Claude!"

    async def test_complete_with_tools(self) -> None:
        """Passes tools to Anthropic API; result has tool_calls populated."""
        from unittest.mock import AsyncMock, MagicMock

        mock_response = _make_anthropic_response(
            content=[
                MockToolUseBlock("tc_abc", "read_file", {"path": "/tmp/test.txt"}),
            ],
        )
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        self.provider._client = mock_client

        tools = [
            ToolSpec(
                name="read_file",
                description="Read file",
                parameters={"type": "object"},
            )
        ]
        request = ChatRequest(
            messages=[Message(role="user", content="Read a file")],
            tools=tools,
        )
        result = await self.provider.complete(request)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "tools" in call_kwargs

        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "read_file"

    async def test_complete_system_passed_as_system_param(self) -> None:
        """System message goes to system parameter, NOT into messages list."""
        from unittest.mock import AsyncMock, MagicMock

        mock_response = _make_anthropic_response(
            content=[MockTextBlock("Sure!")],
        )
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        self.provider._client = mock_client

        request = ChatRequest(
            messages=[
                Message(role="system", content="You are helpful."),
                Message(role="user", content="Hello"),
            ],
        )
        await self.provider.complete(request)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "system" in call_kwargs
        for msg in call_kwargs["messages"]:
            assert msg["role"] != "system"

    async def test_complete_usage_populated(self) -> None:
        """usage has input_tokens=200, output_tokens=100, total_tokens=300."""
        from unittest.mock import AsyncMock, MagicMock

        mock_response = _make_anthropic_response(
            content=[MockTextBlock("Response")],
            input_tokens=200,
            output_tokens=100,
        )
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        self.provider._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        result = await self.provider.complete(request)

        assert result.usage is not None
        assert result.usage.input_tokens == 200
        assert result.usage.output_tokens == 100
        assert result.usage.total_tokens == 300


# ---------------------------------------------------------------------------
# TestToolResultRepair
# ---------------------------------------------------------------------------


class TestToolResultRepair:
    """Tests for _find_missing_tool_results() and _create_synthetic_result()."""

    def setup_method(self) -> None:
        self.provider = AnthropicProvider(config={})

    def test_find_missing_tool_results(self) -> None:
        """Detects missing tool result and returns tuple with call_id='tc_1'."""
        messages = [
            Message(
                role="assistant",
                content=[
                    ToolCallBlock(
                        id="tc_1",
                        name="read_file",
                        input={"path": "/tmp/x"},
                    )
                ],
            )
        ]
        result = self.provider._find_missing_tool_results(messages)

        assert len(result) == 1
        msg_idx, call_id, tool_name, tool_input = result[0]
        assert call_id == "tc_1"
        assert tool_name == "read_file"
        assert tool_input == {"path": "/tmp/x"}

    def test_no_missing_when_result_present(self) -> None:
        """Returns empty list when all tool calls have matching results."""
        messages = [
            Message(
                role="assistant",
                content=[ToolCallBlock(id="tc_1", name="read_file", input={})],
            ),
            Message(role="tool", content="File contents", tool_call_id="tc_1"),
        ]
        result = self.provider._find_missing_tool_results(messages)
        assert result == []

    def test_repaired_ids_not_detected_again(self) -> None:
        """IDs already in _repaired_tool_ids are excluded from detection."""
        self.provider._repaired_tool_ids.add("tc_1")
        messages = [
            Message(
                role="assistant",
                content=[ToolCallBlock(id="tc_1", name="read_file", input={})],
            )
        ]
        result = self.provider._find_missing_tool_results(messages)
        assert result == []


# ---------------------------------------------------------------------------
# TestRateLimitState
# ---------------------------------------------------------------------------


class TestRateLimitState:
    """Tests for _RateLimitState and maybe_throttle pre-emptive throttling."""

    async def test_no_throttle_when_no_retry_after(self) -> None:
        """No delay when retry_after is not set. Elapsed time should be < 0.1s."""
        import time

        state = _RateLimitState()
        start = time.monotonic()
        await state.maybe_throttle()
        elapsed = time.monotonic() - start

        assert elapsed < 0.1

    async def test_throttle_when_retry_after_set(self) -> None:
        """Sets retry_after=0.1 (100ms); verifies elapsed >= 0.08s and retry_after cleared."""
        import time

        state = _RateLimitState()
        state.retry_after = 0.1
        start = time.monotonic()
        await state.maybe_throttle()
        elapsed = time.monotonic() - start

        assert elapsed >= 0.08
        assert state.retry_after is None

    def test_update_from_response_with_headers(self) -> None:
        """MockResponse with headers dict updates all state fields correctly."""

        class _MockResponseWithHeaders:
            def __init__(self) -> None:
                self.headers = {
                    "anthropic-ratelimit-requests-limit": "100",
                    "anthropic-ratelimit-requests-remaining": "50",
                    "anthropic-ratelimit-tokens-limit": "100000",
                    "anthropic-ratelimit-tokens-remaining": "80000",
                }

        state = _RateLimitState()
        state.update_from_response(_MockResponseWithHeaders())

        assert state.requests_limit == 100
        assert state.requests_remaining == 50
        assert state.tokens_limit == 100000
        assert state.tokens_remaining == 80000

    def test_update_from_response_without_headers(self) -> None:
        """MagicMock(spec=[]) has no headers attribute; should not crash; state stays at defaults."""
        from unittest.mock import MagicMock

        state = _RateLimitState()
        response = MagicMock(spec=[])
        state.update_from_response(response)  # must not raise

        assert state.requests_limit is None
        assert state.requests_remaining is None
        assert state.tokens_limit is None
        assert state.tokens_remaining is None


# ---------------------------------------------------------------------------
# TestExtendedThinking
# ---------------------------------------------------------------------------


class TestExtendedThinking:
    """Tests for extended thinking (thinking_budget) parameter handling."""

    def _make_provider(self, **config_overrides) -> AnthropicProvider:
        """Create an AnthropicProvider with optional config overrides."""
        config = {"api_key": "test-key", **config_overrides}
        return AnthropicProvider(config=config)

    async def test_thinking_budget_from_config(self) -> None:
        """Provider with thinking_budget=10000 passes thinking param to API call."""
        from unittest.mock import AsyncMock, MagicMock

        provider = self._make_provider(thinking_budget=10000)
        mock_response = _make_anthropic_response(
            content=[MockTextBlock("I thought about it carefully.")],
        )
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Think carefully.")])
        await provider.complete(request)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "thinking" in call_kwargs
        assert call_kwargs["thinking"] == {"type": "enabled", "budget_tokens": 10000}

    async def test_thinking_budget_from_kwargs(self) -> None:
        """Provider without thinking_budget uses thinking_budget kwarg passed to complete()."""
        from unittest.mock import AsyncMock, MagicMock

        provider = self._make_provider()
        mock_response = _make_anthropic_response(
            content=[MockTextBlock("Done.")],
        )
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        await provider.complete(request, thinking_budget=5000)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "thinking" in call_kwargs
        assert call_kwargs["thinking"]["budget_tokens"] == 5000

    async def test_no_thinking_when_budget_not_set(self) -> None:
        """Provider without thinking_budget does not include thinking in the API call."""
        from unittest.mock import AsyncMock, MagicMock

        provider = self._make_provider()
        mock_response = _make_anthropic_response(
            content=[MockTextBlock("Simple response.")],
        )
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        await provider.complete(request)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "thinking" not in call_kwargs

    def test_thinking_block_in_response(self) -> None:
        """_convert_to_chat_response with thinking + text blocks produces 2-block content list."""
        provider = self._make_provider()
        response = _make_anthropic_response(
            content=[
                MockThinkingBlock(thinking="Step 1: analyze...", signature="sig_1"),
                MockTextBlock("Here is the answer."),
            ],
        )
        result = provider._convert_to_chat_response(response)

        assert result.content is not None
        assert len(result.content) == 2

        thinking_block = result.content[0]
        assert isinstance(thinking_block, ThinkingBlock)
        assert thinking_block.thinking == "Step 1: analyze..."
        assert thinking_block.signature == "sig_1"

        text_block = result.content[1]
        assert isinstance(text_block, TextBlock)
        assert text_block.text == "Here is the answer."
