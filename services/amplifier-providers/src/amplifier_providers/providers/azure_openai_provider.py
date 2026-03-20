"""Azure OpenAI provider stub — real implementation handled by the Azure OpenAI SDK."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import ChatRequest, ChatResponse, provider

__all__ = ["AzureOpenAIProvider"]


@provider
class AzureOpenAIProvider:
    """Stub for the Azure OpenAI provider. Use the real Azure OpenAI SDK integration."""

    name = "azure_openai"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Not implemented — use the real Azure OpenAI provider implementation."""
        raise NotImplementedError(
            "AzureOpenAIProvider.complete() is not implemented. "
            "Use the real Azure OpenAI SDK integration."
        )
