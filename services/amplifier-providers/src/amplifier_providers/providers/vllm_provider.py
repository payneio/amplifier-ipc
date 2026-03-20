"""vLLM provider stub — real implementation handled by the vLLM API client."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import ChatRequest, ChatResponse, provider

__all__ = ["VllmProvider"]


@provider
class VllmProvider:
    """Stub for the vLLM provider. Use the real vLLM API client integration."""

    name = "vllm"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Not implemented — use the real vLLM provider implementation."""
        raise NotImplementedError(
            "VllmProvider.complete() is not implemented. "
            "Use the real vLLM API client integration."
        )
