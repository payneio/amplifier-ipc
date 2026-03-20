"""Tests for MockProvider discovery and behavior."""

from __future__ import annotations

from amplifier_ipc_protocol import ChatRequest, ChatResponse, Message
from amplifier_ipc_protocol.discovery import scan_package


def test_scan_package_discovers_mock() -> None:
    """scan_package must discover MockProvider with name='mock'."""
    components = scan_package("amplifier_providers")
    providers = components.get("provider", [])
    assert providers, "No providers discovered by scan_package"

    names = [getattr(p, "name", None) for p in providers]
    assert "mock" in names, f"MockProvider not discovered; found providers: {names}"


def test_scan_package_mock_is_provider_instance() -> None:
    """Discovered mock provider must have the correct name attribute."""
    components = scan_package("amplifier_providers")
    providers = components.get("provider", [])
    mock = next((p for p in providers if getattr(p, "name", None) == "mock"), None)
    assert mock is not None, "MockProvider not found in scan_package results"
    assert mock.name == "mock"


async def test_describe_reports_mock_provider() -> None:
    """Server.describe must report mock in capabilities.providers."""
    from amplifier_ipc_protocol.server import Server

    server = Server("amplifier_providers")
    result = await server._handle_describe()

    assert "capabilities" in result
    capabilities = result["capabilities"]
    assert "providers" in capabilities

    provider_names = [p.get("name") for p in capabilities["providers"]]
    assert "mock" in provider_names, (
        f"'mock' not in describe providers: {provider_names}"
    )


async def test_mock_provider_complete_returns_chat_response() -> None:
    """MockProvider.complete() must return a ChatResponse."""
    from amplifier_providers.providers.mock import MockProvider

    provider = MockProvider()
    request = ChatRequest(
        messages=[Message(role="user", content="Hello, how are you?")]
    )
    response = await provider.complete(request)

    assert isinstance(response, ChatResponse)


async def test_mock_provider_complete_has_content() -> None:
    """MockProvider.complete() must return ChatResponse with non-empty content."""
    from amplifier_providers.providers.mock import MockProvider

    provider = MockProvider()
    request = ChatRequest(
        messages=[Message(role="user", content="Tell me something")]
    )
    response = await provider.complete(request)

    assert response.content is not None, "ChatResponse.content must not be None"
    assert len(response.content) > 0, "ChatResponse.content must not be empty"


async def test_mock_provider_complete_has_usage() -> None:
    """MockProvider.complete() must return ChatResponse with usage info."""
    from amplifier_providers.providers.mock import MockProvider

    provider = MockProvider()
    request = ChatRequest(
        messages=[Message(role="user", content="Hello")]
    )
    response = await provider.complete(request)

    assert response.usage is not None, "ChatResponse.usage must not be None"


async def test_mock_provider_tracks_call_count() -> None:
    """MockProvider must track call_count incrementing with each complete() call."""
    from amplifier_providers.providers.mock import MockProvider

    provider = MockProvider()
    assert provider.call_count == 0

    request = ChatRequest(messages=[Message(role="user", content="test")])
    await provider.complete(request)
    assert provider.call_count == 1

    await provider.complete(request)
    assert provider.call_count == 2


async def test_mock_provider_read_keyword_produces_tool_call() -> None:
    """MockProvider must return ToolCall when 'read' is in last message content."""
    from amplifier_providers.providers.mock import MockProvider

    provider = MockProvider()
    request = ChatRequest(
        messages=[Message(role="user", content="Please read the file")]
    )
    response = await provider.complete(request)

    assert response.tool_calls is not None, (
        "Expected tool_calls when 'read' keyword present"
    )
    assert len(response.tool_calls) > 0, "Expected at least one tool call"


async def test_mock_provider_no_read_keyword_returns_text() -> None:
    """MockProvider must return text content when no 'read' keyword present."""
    from amplifier_providers.providers.mock import MockProvider

    provider = MockProvider()
    request = ChatRequest(
        messages=[Message(role="user", content="What is the weather?")]
    )
    response = await provider.complete(request)

    assert response.content is not None
    # Should be a list of content blocks
    assert isinstance(response.content, list), "Content should be a list of blocks"
    # First block should be a text block
    first_block = response.content[0]
    assert hasattr(first_block, "text"), "First block should have a text attribute"


async def test_mock_provider_cycles_through_responses() -> None:
    """MockProvider must cycle through response texts."""
    from amplifier_providers.providers.mock import MockProvider

    provider = MockProvider()
    request = ChatRequest(
        messages=[Message(role="user", content="Hello")]
    )

    # Make multiple calls and collect response texts
    texts = set()
    for _ in range(len(provider.responses) + 1):
        response = await provider.complete(request)
        if response.content and isinstance(response.content, list):
            block = response.content[0]
            if hasattr(block, "text"):
                texts.add(block.text)

    # Should have cycled through at least 2 different responses
    assert len(texts) >= 2, f"Expected cycling through responses, got: {texts}"
