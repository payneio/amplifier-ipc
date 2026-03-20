"""OpenAI provider stub — requires SDK and amplifier_lite internals not yet ported."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import provider, ChatRequest, ChatResponse, TextBlock, Usage


@provider
class OpenAIProvider:
    """OpenAI provider (stub — not yet implemented in IPC service)."""

    name = "openai"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        raise NotImplementedError(
            "OpenAIProvider stub: not yet implemented in IPC service. "
            "Requires openai SDK and amplifier_lite error handling."
        )
