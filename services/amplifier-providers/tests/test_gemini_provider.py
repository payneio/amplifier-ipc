"""Tests for GeminiProvider._convert_messages() and related methods."""

from __future__ import annotations

from amplifier_ipc.protocol import ChatRequest, ChatResponse, Message
from amplifier_ipc.protocol.models import ToolSpec

from amplifier_providers.providers.gemini_provider import GeminiProvider


# ---------------------------------------------------------------------------
# Mock helpers for _convert_to_chat_response tests
# ---------------------------------------------------------------------------


class MockFunctionCall:
    """Simulates a Gemini function_call part."""

    def __init__(self, name: str, args: dict) -> None:
        self.name = name
        self.args = args


class MockPart:
    """Simulates a Gemini response Part object."""

    def __init__(
        self,
        text: str | None = None,
        function_call: MockFunctionCall | None = None,
        thought: bool = False,
    ) -> None:
        self.text = text
        self.function_call = function_call
        # thought attribute is deliberately absent when False,
        # matching real Gemini SDK behaviour (production code uses
        # getattr(part, "thought", False) to check for presence).
        if thought:
            self.thought = True


class MockCandidate:
    """Simulates a Gemini response Candidate."""

    def __init__(self, parts: list, finish_reason: str = "STOP") -> None:
        self.content = MockContent(parts=parts, role="model")
        self.finish_reason = finish_reason


class MockContent:
    """Simulates a Gemini Content object."""

    def __init__(self, parts: list, role: str = "user") -> None:
        self.parts = parts
        self.role = role


class MockUsageMetadata:
    """Simulates Gemini UsageMetadata."""

    def __init__(
        self,
        prompt_token_count: int = 100,
        candidates_token_count: int = 50,
        total_token_count: int = 150,
    ) -> None:
        self.prompt_token_count = prompt_token_count
        self.candidates_token_count = candidates_token_count
        self.total_token_count = total_token_count


class MockGeminiResponse:
    """Simulates a Gemini generate_content response."""

    def __init__(
        self,
        candidates: list,
        usage_metadata: MockUsageMetadata | None = None,
    ) -> None:
        self.candidates = candidates
        self.usage_metadata = usage_metadata or MockUsageMetadata()


def _make_gemini_response(
    parts: list | None = None,
    finish_reason: str = "STOP",
    prompt_token_count: int = 100,
    candidates_token_count: int = 50,
    total_token_count: int = 150,
) -> MockGeminiResponse:
    """Helper to create a MockGeminiResponse with optional usage overrides."""
    parts = parts or [MockPart(text="Hello!")]
    candidate = MockCandidate(parts=parts, finish_reason=finish_reason)
    return MockGeminiResponse(
        candidates=[candidate],
        usage_metadata=MockUsageMetadata(
            prompt_token_count=prompt_token_count,
            candidates_token_count=candidates_token_count,
            total_token_count=total_token_count,
        ),
    )


# ---------------------------------------------------------------------------
# TestGeminiConvertMessages
# ---------------------------------------------------------------------------


class TestGeminiConvertMessages:
    """Tests for GeminiProvider._convert_messages()."""

    def setup_method(self) -> None:
        """Create a provider instance for each test (no API key needed)."""
        self.provider = GeminiProvider(config={})

    def test_simple_user_message(self) -> None:
        """A single user message converts to Gemini Content with role='user'."""
        messages = [Message(role="user", content="Hello, Gemini!")]
        contents, system_instruction = self.provider._convert_messages(messages)

        assert len(contents) == 1
        assert contents[0]["role"] == "user"
        assert system_instruction is None

    def test_system_message_extracted(self) -> None:
        """System messages are extracted separately, not in the conversation list."""
        messages = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello"),
        ]
        contents, system_instruction = self.provider._convert_messages(messages)

        # System message should NOT be in contents
        roles = [c["role"] for c in contents]
        assert "system" not in roles

        # System content should be extracted as system_instruction
        assert system_instruction == "You are a helpful assistant."

        # Only user message remains
        assert len(contents) == 1
        assert contents[0]["role"] == "user"

    def test_tool_result_message(self) -> None:
        """Tool result message converts to a function_response part in a 'user' Content."""
        tool_call_id = "gemini_call_abc123"
        messages = [
            Message(
                role="tool",
                content="The file contents are: hello world",
                tool_call_id=tool_call_id,
            )
        ]
        contents, system_instruction = self.provider._convert_messages(messages)

        assert len(contents) == 1
        msg = contents[0]
        assert msg["role"] == "user"
        # Parts should contain a function_response
        parts = msg["parts"]
        assert len(parts) >= 1
        # The part should represent a function_response
        part = parts[0]
        assert hasattr(part, "function_response") or (
            isinstance(part, dict) and "function_response" in part
        )


# ---------------------------------------------------------------------------
# TestGeminiConvertTools
# ---------------------------------------------------------------------------


class TestGeminiConvertTools:
    """Tests for GeminiProvider._convert_tools_from_request()."""

    def setup_method(self) -> None:
        self.provider = GeminiProvider(config={})

    def test_single_tool(self) -> None:
        """A single ToolSpec converts to Gemini FunctionDeclaration format."""
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
        # Each tool should be a FunctionDeclaration-like object
        assert tool.name == "read_file"
        assert tool.description == "Read the contents of a file"

    def test_empty_tools(self) -> None:
        """Empty tool list returns empty list."""
        result = self.provider._convert_tools_from_request([])
        assert result == []


# ---------------------------------------------------------------------------
# TestGeminiSyntheticToolCallIds
# ---------------------------------------------------------------------------


class TestGeminiSyntheticToolCallIds:
    """Tests that Gemini provider generates synthetic tool call IDs."""

    def setup_method(self) -> None:
        self.provider = GeminiProvider(config={})

    def test_generates_synthetic_ids(self) -> None:
        """Tool call responses must have IDs starting with 'gemini_call_'."""
        function_call = MockFunctionCall(
            name="read_file", args={"path": "/tmp/test.txt"}
        )
        parts = [MockPart(function_call=function_call)]
        response = _make_gemini_response(parts=parts)

        result = self.provider._convert_to_chat_response(response)

        assert result.tool_calls is not None
        assert len(result.tool_calls) >= 1
        assert result.tool_calls[0].id.startswith("gemini_call_")


# ---------------------------------------------------------------------------
# TestGeminiComplete
# ---------------------------------------------------------------------------


class TestGeminiComplete:
    """Tests for GeminiProvider.complete() — uses mocked Gemini model."""

    def setup_method(self) -> None:
        """Create provider with a fake API key; real model is injected per test."""
        self.provider = GeminiProvider(config={"api_key": "test-key"})

    def test_complete_returns_chat_response(self) -> None:
        """complete() returns a ChatResponse with correct text content."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        mock_response = _make_gemini_response(
            parts=[MockPart(text="Hello from Gemini!")]
        )
        mock_model = MagicMock()
        mock_model.generate_content_async = AsyncMock(return_value=mock_response)
        self.provider._model = mock_model

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        result = asyncio.run(self.provider.complete(request))

        assert isinstance(result, ChatResponse)
        assert result.text == "Hello from Gemini!"
