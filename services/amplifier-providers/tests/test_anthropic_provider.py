"""Tests for AnthropicProvider._convert_messages() and related methods."""

from __future__ import annotations

from amplifier_ipc_protocol import Message
from amplifier_ipc_protocol.models import ThinkingBlock, ToolCallBlock

from amplifier_providers.providers.anthropic_provider import AnthropicProvider


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
