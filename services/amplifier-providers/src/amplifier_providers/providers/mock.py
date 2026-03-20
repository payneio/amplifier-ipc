"""Mock provider for testing without API calls."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import ChatRequest
from amplifier_ipc_protocol import ChatResponse
from amplifier_ipc_protocol import TextBlock
from amplifier_ipc_protocol import ToolCall
from amplifier_ipc_protocol import Usage
from amplifier_ipc_protocol import provider

__all__ = ["MockProvider"]


@provider
class MockProvider:
    """Mock provider for testing without API calls."""

    name = "mock"

    def __init__(self, config: dict | None = None) -> None:
        """Initialize Mock provider with optional config dict."""
        default_responses = [
            "I'll help you with that task.",
            "Task completed successfully.",
            "Here's the result of your request.",
        ]
        self.responses = (config or {}).get("responses", default_responses)
        self.call_count = 0

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Generate a mock completion from ChatRequest."""
        self.call_count += 1

        # Check last message content for simple pattern matching
        last_message = request.messages[-1] if request.messages else None
        content = ""
        if last_message and isinstance(last_message.content, str):
            content = last_message.content
        elif last_message and isinstance(last_message.content, list):
            # Extract text from TextBlock only
            for block in last_message.content:
                if block.type == "text":
                    content = block.text
                    break

        # Simple pattern matching for tool calls
        tool_calls = []
        if "read" in content.lower():
            tool_calls.append(
                ToolCall(id="mock_tool_1", name="read", arguments={"path": "test.txt"})
            )

        # Generate response
        if tool_calls:
            # Response with tool calls
            response = ChatResponse(
                content=[TextBlock(text="I'll read that file for you.")],
                tool_calls=tool_calls,
                usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15),
            )
        else:
            # Regular text response
            response_text = self.responses[(self.call_count - 1) % len(self.responses)]
            response = ChatResponse(
                content=[TextBlock(text=response_text)],
                usage=Usage(input_tokens=10, output_tokens=20, total_tokens=30),
            )

        return response
