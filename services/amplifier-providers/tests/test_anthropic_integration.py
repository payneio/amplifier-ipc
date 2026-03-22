"""Integration tests for AnthropicProvider through the IPC Server path.

Tests the full provider through the JSON-RPC server: describe sees anthropic,
provider.complete routes correctly, ChatResponse comes back.

Note: Server does not yet expose _handle_provider_complete, so tests are adapted
to use the actual server dispatch pattern: Server discovers providers via
scan_package, the provider instance is obtained from server._components, the
Anthropic HTTP client is mocked, and complete() is called directly.  The result
is serialised with model_dump(mode='json') so dict-key assertions work as
described in the spec.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from amplifier_ipc_protocol import ChatRequest, ChatResponse, Message, ToolSpec
from amplifier_ipc_protocol.server import Server


# ---------------------------------------------------------------------------
# Minimal Anthropic API response mocks (same contract as test_anthropic_provider)
# ---------------------------------------------------------------------------


class _MockUsage:
    """Simulates an Anthropic API usage object."""

    def __init__(
        self,
        input_tokens: int = 10,
        output_tokens: int = 5,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class _MockTextBlock:
    """Simulates an Anthropic text content block."""

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _MockToolUseBlock:
    """Simulates an Anthropic tool_use content block."""

    def __init__(self, tool_id: str, name: str, input: dict[str, Any]) -> None:  # noqa: A002
        self.type = "tool_use"
        self.id = tool_id
        self.name = name
        self.input = input


class _MockResponse:
    """Simulates an Anthropic Messages API response object."""

    def __init__(
        self,
        content: list[Any],
        stop_reason: str = "end_turn",
        usage: _MockUsage | None = None,
        model: str = "claude-test",
    ) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage or _MockUsage()
        self.model = model


# ---------------------------------------------------------------------------
# Helper: locate the AnthropicProvider instance in server components
# ---------------------------------------------------------------------------


def _get_anthropic_provider(server: Server) -> Any:
    """Return the AnthropicProvider instance discovered by *server*, or None."""
    providers = server._components.get("provider", [])
    return next((p for p in providers if getattr(p, "name", None) == "anthropic"), None)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


async def test_describe_reports_anthropic_provider() -> None:
    """Server._handle_describe() reports 'anthropic' in capabilities.providers."""
    server = Server("amplifier_providers")
    result = await server._handle_describe()

    assert "capabilities" in result, "describe result must have 'capabilities' key"
    providers = result["capabilities"]["providers"]
    provider_names = [p.get("name") for p in providers]
    assert "anthropic" in provider_names, (
        f"'anthropic' not found in describe providers: {provider_names}"
    )


async def test_provider_complete_routes_to_anthropic() -> None:
    """Server discovers AnthropicProvider; complete() returns ChatResponse with correct text.

    Adaptation note: Server._handle_provider_complete() is not yet implemented.
    The test accesses server._components to obtain the provider instance directly,
    then calls complete() — the equivalent of what the server handler would do.
    """
    server = Server("amplifier_providers")
    provider = _get_anthropic_provider(server)
    assert provider is not None, "AnthropicProvider not found in server._components"

    mock_response = _MockResponse(
        content=[_MockTextBlock("Integration test response")],
        usage=_MockUsage(input_tokens=10, output_tokens=5),
    )
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    provider._client = mock_client

    request = ChatRequest(messages=[Message(role="user", content="Hello")])
    result: ChatResponse = await provider.complete(request)
    result_dict = result.model_dump(mode="json")

    assert result_dict["text"] == "Integration test response", (
        f"Expected 'Integration test response', got: {result_dict['text']!r}"
    )
    assert result_dict["content_blocks"] is not None
    assert len(result_dict["content_blocks"]) >= 1
    assert result_dict["content_blocks"][0]["text"] == "Integration test response"


async def test_provider_complete_returns_usage() -> None:
    """complete() returns correct usage: input_tokens=100, output_tokens=50."""
    server = Server("amplifier_providers")
    provider = _get_anthropic_provider(server)
    assert provider is not None, "AnthropicProvider not found in server._components"

    mock_response = _MockResponse(
        content=[_MockTextBlock("Response with usage")],
        usage=_MockUsage(input_tokens=100, output_tokens=50),
    )
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    provider._client = mock_client

    request = ChatRequest(messages=[Message(role="user", content="Hello")])
    result: ChatResponse = await provider.complete(request)
    result_dict = result.model_dump(mode="json")

    assert result_dict["usage"]["input_tokens"] == 100, (
        f"Expected input_tokens=100, got {result_dict['usage']['input_tokens']}"
    )
    assert result_dict["usage"]["output_tokens"] == 50, (
        f"Expected output_tokens=50, got {result_dict['usage']['output_tokens']}"
    )


async def test_provider_complete_with_tool_calls() -> None:
    """complete() with text + tool_use blocks returns tool_calls with read_file."""
    server = Server("amplifier_providers")
    provider = _get_anthropic_provider(server)
    assert provider is not None, "AnthropicProvider not found in server._components"

    mock_response = _MockResponse(
        content=[
            _MockTextBlock("I'll read that file for you."),
            _MockToolUseBlock(
                tool_id="toolu_int",
                name="read_file",
                input={"path": "test.txt"},
            ),
        ],
        usage=_MockUsage(),
    )
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    provider._client = mock_client

    read_file_tool = ToolSpec(
        name="read_file",
        description="Read the contents of a file",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
    )
    request = ChatRequest(
        messages=[Message(role="user", content="Read test.txt")],
        tools=[read_file_tool],
    )
    result: ChatResponse = await provider.complete(request)
    # Use by_alias=True so ToolCall.name is serialised under its serialization_alias "tool"
    result_dict = result.model_dump(mode="json", by_alias=True)

    # ToolCall serialises name via serialization_alias="tool"
    assert result_dict["tool_calls"] is not None, "Expected tool_calls to be populated"
    assert len(result_dict["tool_calls"]) == 1, (
        f"Expected 1 tool call, got {len(result_dict['tool_calls'])}"
    )
    assert result_dict["tool_calls"][0]["tool"] == "read_file", (
        f"Expected tool='read_file', got: {result_dict['tool_calls'][0]!r}"
    )
