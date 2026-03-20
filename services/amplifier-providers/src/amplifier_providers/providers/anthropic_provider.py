"""Anthropic provider stub — real implementation handled by the Anthropic SDK."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import ChatRequest, ChatResponse, provider

__all__ = ["AnthropicProvider"]


@provider
class AnthropicProvider:
    """Stub for the Anthropic provider. Use the real Anthropic SDK integration."""

    name = "anthropic"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Not implemented — use the real Anthropic provider implementation."""
        raise NotImplementedError(
            "AnthropicProvider.complete() is not implemented. "
            "Use the real Anthropic SDK integration."
        )
