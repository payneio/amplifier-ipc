"""Tests for AnthropicProvider._convert_messages() and related methods."""

from __future__ import annotations

from amplifier_ipc_protocol import Message
from amplifier_ipc_protocol.models import (
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolSpec,
)

from amplifier_providers.providers.anthropic_provider import AnthropicProvider


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
