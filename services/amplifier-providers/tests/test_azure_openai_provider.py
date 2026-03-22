"""Tests for AzureOpenAIProvider — init, message conversion (reused from OpenAI), and complete()."""

from __future__ import annotations

import json

import pytest
from amplifier_ipc.protocol import ChatRequest, ChatResponse, Message

from amplifier_providers.providers.azure_openai_provider import AzureOpenAIProvider


# ---------------------------------------------------------------------------
# Mock helpers (same shape as OpenAI mock helpers)
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


def _make_azure_response(
    content: str | None = None,
    tool_calls: list | None = None,
    finish_reason: str = "stop",
) -> MockResponse:
    """Helper to create a MockResponse for Azure tests."""
    message = MockMessage(content=content, tool_calls=tool_calls)
    choice = MockChoice(message=message, finish_reason=finish_reason)
    return MockResponse(choices=[choice])


# ---------------------------------------------------------------------------
# TestAzureOpenAIInit
# ---------------------------------------------------------------------------


class TestAzureOpenAIInit:
    """Tests for AzureOpenAIProvider.__init__()."""

    def test_init_with_api_key(self) -> None:
        """Provider stores api_key, azure_endpoint, and api_version from config."""
        provider = AzureOpenAIProvider(
            config={
                "api_key": "test-azure-key",
                "azure_endpoint": "https://myresource.openai.azure.com/",
                "api_version": "2024-02-01",
            }
        )

        assert provider._api_key == "test-azure-key"
        assert provider._azure_endpoint == "https://myresource.openai.azure.com/"
        assert provider._api_version == "2024-02-01"

    def test_init_without_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Provider falls back to environment variables when config is empty."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "env-azure-key")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://envresource.openai.azure.com/")
        monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

        provider = AzureOpenAIProvider()

        assert provider._api_key == "env-azure-key"
        assert provider._azure_endpoint == "https://envresource.openai.azure.com/"
        assert provider._api_version == "2024-05-01-preview"


# ---------------------------------------------------------------------------
# TestAzureOpenAIConvertMessages
# ---------------------------------------------------------------------------


class TestAzureOpenAIConvertMessages:
    """Tests that AzureOpenAIProvider reuses OpenAI message conversion."""

    def setup_method(self) -> None:
        """Create provider with minimal config (no API key needed for conversion)."""
        self.provider = AzureOpenAIProvider(config={})

    def test_simple_user_message(self) -> None:
        """A single user message converts to OpenAI format (reuses OpenAI conversion)."""
        messages = [Message(role="user", content="Hello, Azure!")]
        result = self.provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello, Azure!"


# ---------------------------------------------------------------------------
# TestAzureOpenAIComplete
# ---------------------------------------------------------------------------


class TestAzureOpenAIComplete:
    """Tests for AzureOpenAIProvider.complete() — uses mocked AsyncAzureOpenAI client."""

    def setup_method(self) -> None:
        """Create provider with fake credentials; real client is injected per test."""
        self.provider = AzureOpenAIProvider(
            config={
                "api_key": "test-azure-key",
                "azure_endpoint": "https://myresource.openai.azure.com/",
                "api_version": "2024-02-01",
            }
        )

    def test_complete_returns_chat_response(self) -> None:
        """complete() returns a ChatResponse with correct text content."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        mock_response = _make_azure_response(content="Hello from Azure!")
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        self.provider._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        result = asyncio.run(self.provider.complete(request))

        assert isinstance(result, ChatResponse)
        assert result.text == "Hello from Azure!"
