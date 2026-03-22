"""Tests for GitHubCopilotProvider — init, message conversion (reused from OpenAI), and complete()."""

from __future__ import annotations

import json

import pytest
from amplifier_ipc.protocol import ChatRequest, ChatResponse, Message

from amplifier_providers.providers.github_copilot_provider import GitHubCopilotProvider


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
        model: str = "gpt-4o-copilot",
    ) -> None:
        self.choices = choices
        self.usage = usage or MockUsage()
        self.model = model


def _make_copilot_response(
    content: str | None = None,
    tool_calls: list | None = None,
    finish_reason: str = "stop",
) -> MockResponse:
    """Helper to create a MockResponse for Copilot tests."""
    message = MockMessage(content=content, tool_calls=tool_calls)
    choice = MockChoice(message=message, finish_reason=finish_reason)
    return MockResponse(choices=[choice])


# ---------------------------------------------------------------------------
# TestGitHubCopilotInit
# ---------------------------------------------------------------------------


class TestGitHubCopilotInit:
    """Tests for GitHubCopilotProvider.__init__()."""

    def test_init_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Provider stores github_token from GITHUB_TOKEN env var; client is None (lazy)."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_env_token")

        provider = GitHubCopilotProvider()

        assert provider._github_token == "ghp_env_token"
        assert provider._client is None

    def test_init_with_token(self) -> None:
        """Provider stores github_token from config dict; client starts as None."""
        provider = GitHubCopilotProvider(config={"github_token": "ghp_config_token"})

        assert provider._github_token == "ghp_config_token"
        assert provider._client is None


# ---------------------------------------------------------------------------
# TestGitHubCopilotConvertMessages
# ---------------------------------------------------------------------------


class TestGitHubCopilotConvertMessages:
    """Tests that GitHubCopilotProvider reuses OpenAI message conversion."""

    def setup_method(self) -> None:
        """Create provider with minimal config (no token needed for conversion)."""
        self.provider = GitHubCopilotProvider(config={})

    def test_simple_user_message(self) -> None:
        """A single user message converts to OpenAI-compatible format (reuses OpenAI conversion)."""
        messages = [Message(role="user", content="Hello, Copilot!")]
        result = self.provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello, Copilot!"


# ---------------------------------------------------------------------------
# TestGitHubCopilotComplete
# ---------------------------------------------------------------------------


class TestGitHubCopilotComplete:
    """Tests for GitHubCopilotProvider.complete() — uses mocked OpenAI client."""

    def setup_method(self) -> None:
        """Create provider with a fake token; real client is injected per test."""
        self.provider = GitHubCopilotProvider(config={"github_token": "ghp_test_token"})

    def test_complete_returns_chat_response(self) -> None:
        """complete() returns a ChatResponse with correct text content."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        mock_response = _make_copilot_response(content="Hello from Copilot!")
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        self.provider._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        result = asyncio.run(self.provider.complete(request))

        assert isinstance(result, ChatResponse)
        assert result.text == "Hello from Copilot!"
