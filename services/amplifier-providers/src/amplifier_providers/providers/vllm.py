"""vLLM provider stub — requires SDK and amplifier_lite internals not yet ported."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import provider, ChatRequest, ChatResponse, TextBlock, Usage


@provider
class VLLMProvider:
    """vLLM provider (stub — not yet implemented in IPC service)."""

    name = "vllm"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        raise NotImplementedError(
            "VLLMProvider stub: not yet implemented in IPC service. "
            "Requires vllm client and amplifier_lite error handling."
        )
