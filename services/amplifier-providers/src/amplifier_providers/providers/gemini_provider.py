"""Gemini provider stub — real implementation handled by the Google Gemini SDK."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import ChatRequest, ChatResponse, provider

__all__ = ["GeminiProvider"]


@provider
class GeminiProvider:
    """Stub for the Gemini provider. Use the real Google Gemini SDK integration."""

    name = "gemini"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Not implemented — use the real Gemini provider implementation."""
        raise NotImplementedError(
            "GeminiProvider.complete() is not implemented. "
            "Use the real Google Gemini SDK integration."
        )
