"""Tests for OpenAIProvider._convert_messages() and related methods."""

from __future__ import annotations

import json

from amplifier_ipc_protocol import ChatRequest, ChatResponse, Message
from amplifier_ipc_protocol.models import (
    TextBlock,
    ToolCallBlock,
    ToolSpec,
)

from amplifier_providers.providers.openai_provider import OpenAIProvider


# ---------------------------------------------------------------------------
# Mock helpers for _convert_to_chat_response tests
# ---------------------------------------------------------------------------


class MockFunction:
    """Simulates an OpenAI function call object."""

    def __init__(self, name: str, arguments: dict) -> None:
        self.name = name
        self.arguments = json.dumps(arguments)


class MockToolCall:
    """Simulates an OpenAI tool call object."""

    def __init__(self, tool_id: str, name: str, arguments: dict) -> None:
        self.id = tool_id
        self.type = "function"
        self.function = MockFunction(name, arguments)


class MockMessage:
    """Simulates an OpenAI chat message object."""

    def __init__(
        self,
        content: str | None = None,
        tool_calls: list | None = None,
        role: str = "assistant",
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.role = role


class MockChoice:
    """Simulates an OpenAI response choice."""

    def __init__(self, message: MockMessage, finish_reason: str = "stop") -> None:
        self.message = message
        self.finish_reason = finish_reason


class MockUsage:
    """Simulates an OpenAI API usage object."""

    def __init__(
        self,
        prompt_tokens: int = 100,
        completion_tokens: int = 50,
    ) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


class MockResponse:
    """Simulates an OpenAI chat completions response object."""

    def __init__(
        self,
        choices: list,
        usage: MockUsage | None = None,
        model: str = "gpt-4o",
    ) -> None:
        self.choices = choices
        self.usage = usage or MockUsage()
        self.model = model


def _make_openai_response(
    content: str | None = None,
    tool_calls: list | None = None,
    finish_reason: str = "stop",
    **usage_kwargs,
) -> MockResponse:
    """Helper to create a MockResponse with optional usage overrides."""
    message = MockMessage(content=content, tool_calls=tool_calls)
    choice = MockChoice(message=message, finish_reason=finish_reason)
    return MockResponse(
        choices=[choice],
        usage=MockUsage(**usage_kwargs),
    )


# ---------------------------------------------------------------------------
# TestOpenAIConvertMessages
# ---------------------------------------------------------------------------


class TestOpenAIConvertMessages:
    """Tests for OpenAIProvider._convert_messages()."""

    def setup_method(self) -> None:
        """Create a provider instance for each test (no API key needed)."""
        self.provider = OpenAIProvider(config={})

    def test_simple_user_message(self) -> None:
        """A single user message with string content converts to OpenAI format."""
        messages = [Message(role="user", content="Hello, GPT!")]
        result = self.provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello, GPT!"

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
        assert result[1]["content"] == "The answer is 4."
        assert result[2]["role"] == "user"
        assert result[2]["content"] == "Thanks!"

    def test_system_message_role_preserved(self) -> None:
        """System messages are included in the converted output (OpenAI supports them natively)."""
        messages = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello"),
        ]
        result = self.provider._convert_messages(messages)

        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are a helpful assistant."
        assert result[1]["role"] == "user"

    def test_tool_result_message(self) -> None:
        """Tool result converts to role='tool' message with tool_call_id."""
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
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == tool_call_id
        assert msg["content"] == "The file contents are: hello world"

    def test_assistant_with_tool_calls(self) -> None:
        """Assistant message with ToolCallBlock content produces tool_calls in function format."""
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
        assert "tool_calls" in msg
        assert isinstance(msg["tool_calls"], list)
        assert len(msg["tool_calls"]) == 1

        tc = msg["tool_calls"][0]
        assert tc["type"] == "function"
        assert tc["id"] == "call_xyz789"
        assert tc["function"]["name"] == "read_file"
        # Arguments should be a JSON string
        args = json.loads(tc["function"]["arguments"])
        assert args == {"path": "/tmp/test.txt"}


# ---------------------------------------------------------------------------
# TestOpenAIConvertTools
# ---------------------------------------------------------------------------


class TestOpenAIConvertTools:
    """Tests for OpenAIProvider._convert_tools_from_request()."""

    def setup_method(self) -> None:
        self.provider = OpenAIProvider(config={})

    def test_single_tool(self) -> None:
        """A single ToolSpec converts to OpenAI function format."""
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
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "read_file"
        assert tool["function"]["description"] == "Read the contents of a file"
        assert tool["function"]["parameters"] == {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        }

    def test_empty_tools(self) -> None:
        """Empty tool list returns empty list."""
        result = self.provider._convert_tools_from_request([])
        assert result == []


# ---------------------------------------------------------------------------
# TestOpenAIConvertResponse
# ---------------------------------------------------------------------------


class TestOpenAIConvertResponse:
    """Tests for OpenAIProvider._convert_to_chat_response()."""

    def setup_method(self) -> None:
        self.provider = OpenAIProvider(config={})

    def test_text_response(self) -> None:
        """Text-only response produces ChatResponse with TextBlock; no tool_calls."""
        response = _make_openai_response(content="Hello, world!")
        result = self.provider._convert_to_chat_response(response)

        assert result.tool_calls is None
        assert result.content_blocks is not None
        assert len(result.content_blocks) == 1
        block = result.content_blocks[0]
        assert isinstance(block, TextBlock)
        assert block.text == "Hello, world!"
        assert result.text == "Hello, world!"

    def test_tool_call_response(self) -> None:
        """Tool call produces ToolCallBlock in content_blocks and ToolCall in tool_calls."""
        mock_tool_calls = [
            MockToolCall(
                tool_id="call_abc123",
                name="read_file",
                arguments={"path": "/tmp/test.txt"},
            )
        ]
        response = _make_openai_response(tool_calls=mock_tool_calls)
        result = self.provider._convert_to_chat_response(response)

        # tool_calls list has 1 ToolCall
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.id == "call_abc123"
        assert tc.name == "read_file"
        assert tc.arguments == {"path": "/tmp/test.txt"}

        # content_blocks has ToolCallBlock
        assert result.content_blocks is not None
        tool_call_blocks = [
            b for b in result.content_blocks if isinstance(b, ToolCallBlock)
        ]
        assert len(tool_call_blocks) == 1
        assert tool_call_blocks[0].id == "call_abc123"
        assert tool_call_blocks[0].name == "read_file"

    def test_usage_extraction(self) -> None:
        """Usage tokens are correctly extracted: input=prompt_tokens, output=completion_tokens."""
        response = _make_openai_response(
            content="Response text.",
            prompt_tokens=200,
            completion_tokens=100,
        )
        result = self.provider._convert_to_chat_response(response)

        assert result.usage is not None
        assert result.usage.input_tokens == 200
        assert result.usage.output_tokens == 100
        assert result.usage.total_tokens == 300


# ---------------------------------------------------------------------------
# TestOpenAIComplete
# ---------------------------------------------------------------------------


class TestOpenAIComplete:
    """Tests for OpenAIProvider.complete() — uses mocked OpenAI client."""

    def setup_method(self) -> None:
        """Create provider with a fake API key; real client is injected per test."""
        self.provider = OpenAIProvider(config={"api_key": "test-key"})

    async def test_complete_returns_chat_response(self) -> None:
        """complete() returns a ChatResponse with correct text content."""
        from unittest.mock import AsyncMock, MagicMock

        mock_response = _make_openai_response(content="Hello from GPT!")
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        self.provider._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        result = await self.provider.complete(request)

        assert isinstance(result, ChatResponse)
        assert result.text == "Hello from GPT!"
