"""Tests for OllamaProvider — init, message conversion, response conversion, and complete()."""

from __future__ import annotations

from amplifier_ipc.protocol import ChatRequest, ChatResponse, Message

from amplifier_providers.providers.ollama_provider import OllamaProvider


# ---------------------------------------------------------------------------
# TestOllamaInit
# ---------------------------------------------------------------------------


class TestOllamaInit:
    """Tests for OllamaProvider.__init__() defaults and config."""

    def test_init_defaults(self) -> None:
        """Provider initialises with default host and model when no config given."""
        provider = OllamaProvider()

        assert provider.host == "http://localhost:11434"
        assert provider.model == "llama3.1"
        # Client is lazy — should not be initialised yet
        assert provider._client is None

    def test_init_with_host(self, monkeypatch) -> None:
        """Provider reads host from config dict and from OLLAMA_HOST env var."""
        # From config dict
        provider_from_config = OllamaProvider(
            config={"host": "http://myserver:11434", "model": "mistral"}
        )
        assert provider_from_config.host == "http://myserver:11434"
        assert provider_from_config.model == "mistral"

        # From environment variable
        monkeypatch.setenv("OLLAMA_HOST", "http://envserver:11434")
        provider_from_env = OllamaProvider()
        assert provider_from_env.host == "http://envserver:11434"


# ---------------------------------------------------------------------------
# TestOllamaConvertMessages
# ---------------------------------------------------------------------------


class TestOllamaConvertMessages:
    """Tests for OllamaProvider._convert_messages()."""

    def setup_method(self) -> None:
        """Create a provider instance for each test."""
        self.provider = OllamaProvider(config={})

    def test_simple_user_message(self) -> None:
        """A single user message converts to Ollama format with role and content."""
        messages = [Message(role="user", content="Hello, Ollama!")]
        result = self.provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello, Ollama!"

    def test_system_message(self) -> None:
        """System messages are included in converted output with role='system'."""
        messages = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello"),
        ]
        result = self.provider._convert_messages(messages)

        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are a helpful assistant."
        assert result[1]["role"] == "user"
        assert result[1]["content"] == "Hello"


# ---------------------------------------------------------------------------
# TestOllamaConvertResponse
# ---------------------------------------------------------------------------


class TestOllamaConvertResponse:
    """Tests for OllamaProvider._convert_to_chat_response()."""

    def setup_method(self) -> None:
        self.provider = OllamaProvider(config={})

    def test_text_response(self) -> None:
        """Text-only dict response produces ChatResponse with TextBlock; no tool_calls.

        Ollama returns dicts (not objects). Token counts come from
        eval_count (output) and prompt_eval_count (input).
        """
        response = {
            "message": {
                "role": "assistant",
                "content": "Hello from Ollama!",
            },
            "done": True,
            "eval_count": 42,
            "prompt_eval_count": 10,
        }
        from amplifier_ipc.protocol.models import TextBlock

        result = self.provider._convert_to_chat_response(response)

        assert isinstance(result, ChatResponse)
        assert result.tool_calls is None
        assert result.content_blocks is not None
        assert len(result.content_blocks) == 1
        block = result.content_blocks[0]
        assert isinstance(block, TextBlock)
        assert block.text == "Hello from Ollama!"
        assert result.text == "Hello from Ollama!"

        # Token counts: eval_count → output_tokens, prompt_eval_count → input_tokens
        assert result.usage is not None
        assert result.usage.output_tokens == 42
        assert result.usage.input_tokens == 10


# ---------------------------------------------------------------------------
# TestOllamaComplete
# ---------------------------------------------------------------------------


class TestOllamaComplete:
    """Tests for OllamaProvider.complete() — uses mocked ollama AsyncClient."""

    def setup_method(self) -> None:
        """Create provider; client will be injected per test."""
        self.provider = OllamaProvider(config={})

    def test_complete_returns_chat_response(self) -> None:
        """complete() calls client.chat() and returns a ChatResponse."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        mock_response = {
            "message": {
                "role": "assistant",
                "content": "Hello from Ollama!",
            },
            "done": True,
            "eval_count": 20,
            "prompt_eval_count": 5,
        }
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=mock_response)
        self.provider._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        result = asyncio.run(self.provider.complete(request))

        assert isinstance(result, ChatResponse)
        assert result.text == "Hello from Ollama!"
        # Verify client.chat was called
        mock_client.chat.assert_called_once()
