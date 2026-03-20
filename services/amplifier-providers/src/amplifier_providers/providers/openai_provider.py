"""OpenAI provider stub — real implementation handled by the OpenAI SDK."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import ChatRequest, ChatResponse, provider

__all__ = ["OpenAIProvider"]


@provider
class OpenAIProvider:
    """Stub for the OpenAI provider. Use the real OpenAI SDK integration."""

    name = "openai"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Not implemented — use the real OpenAI provider implementation."""
        raise NotImplementedError(
            "OpenAIProvider.complete() is not implemented. "
            "Use the real OpenAI SDK integration."
        )
