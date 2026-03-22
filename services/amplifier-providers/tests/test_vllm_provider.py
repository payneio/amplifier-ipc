"""Tests for VllmProvider — init, message conversion (reused from OpenAI), and complete()."""

from __future__ import annotations

import pytest
from amplifier_ipc.protocol import ChatRequest, ChatResponse, Message

from amplifier_providers.providers.vllm_provider import VllmProvider


# ---------------------------------------------------------------------------
# Mock helpers (same shape as OpenAI mock helpers)
# ---------------------------------------------------------------------------


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
        model: str = "meta-llama/Llama-3-8b-instruct",
    ) -> None:
        self.choices = choices
        self.usage = usage or MockUsage()
        self.model = model


def _make_vllm_response(
    content: str | None = None,
    finish_reason: str = "stop",
) -> MockResponse:
    """Helper to create a MockResponse for vLLM tests."""
    message = MockMessage(content=content)
    choice = MockChoice(message=message, finish_reason=finish_reason)
    return MockResponse(choices=[choice])


# ---------------------------------------------------------------------------
# TestVllmInit
# ---------------------------------------------------------------------------


class TestVllmInit:
    """Tests for VllmProvider.__init__()."""

    def test_init_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Provider uses default api_base and api_key when no config or env vars set."""
        monkeypatch.delenv("VLLM_API_BASE", raising=False)
        monkeypatch.delenv("VLLM_API_KEY", raising=False)

        provider = VllmProvider(config={})

        assert provider._api_base == "http://localhost:8000/v1"
        assert provider._api_key == "EMPTY"

    def test_init_with_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Provider uses api_base and api_key from config or VLLM_API_BASE/VLLM_API_KEY env vars."""
        monkeypatch.setenv("VLLM_API_BASE", "http://vllm-server:8080/v1")
        monkeypatch.setenv("VLLM_API_KEY", "my-secret-key")

        provider = VllmProvider(config={})

        assert provider._api_base == "http://vllm-server:8080/v1"
        assert provider._api_key == "my-secret-key"


# ---------------------------------------------------------------------------
# TestVllmConvertMessages
# ---------------------------------------------------------------------------


class TestVllmConvertMessages:
    """Tests that VllmProvider reuses OpenAI message conversion."""

    def setup_method(self) -> None:
        """Create provider with minimal config (no API key needed for conversion)."""
        self.provider = VllmProvider(config={})

    def test_simple_user_message(self) -> None:
        """A single user message converts to OpenAI-compatible format (reuses OpenAI conversion)."""
        messages = [Message(role="user", content="Hello, vLLM!")]
        result = self.provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello, vLLM!"


# ---------------------------------------------------------------------------
# TestVllmComplete
# ---------------------------------------------------------------------------


class TestVllmComplete:
    """Tests for VllmProvider.complete() — uses mocked client."""

    def setup_method(self) -> None:
        """Create provider with minimal config; real client is injected per test."""
        self.provider = VllmProvider(config={})

    def test_complete_returns_chat_response(self) -> None:
        """complete() returns a ChatResponse with correct text content."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        mock_response = _make_vllm_response(content="Hello from vLLM!")
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        self.provider._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        result = asyncio.run(self.provider.complete(request))

        assert isinstance(result, ChatResponse)
        assert result.text == "Hello from vLLM!"
