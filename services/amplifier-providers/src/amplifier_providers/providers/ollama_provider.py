"""Ollama provider stub — real implementation handled by the Ollama API client."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import ChatRequest, ChatResponse, provider

__all__ = ["OllamaProvider"]


@provider
class OllamaProvider:
    """Stub for the Ollama provider. Use the real Ollama API client integration."""

    name = "ollama"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Not implemented — use the real Ollama provider implementation."""
        raise NotImplementedError(
            "OllamaProvider.complete() is not implemented. "
            "Use the real Ollama API client integration."
        )
