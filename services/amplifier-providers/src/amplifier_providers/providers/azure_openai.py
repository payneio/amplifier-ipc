"""Azure OpenAI provider stub — requires SDK and amplifier_lite internals not yet ported."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import provider, ChatRequest, ChatResponse, TextBlock, Usage


@provider
class AzureOpenAIProvider:
    """Azure OpenAI provider (stub — not yet implemented in IPC service)."""

    name = "azure_openai"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        raise NotImplementedError(
            "AzureOpenAIProvider stub: not yet implemented in IPC service. "
            "Requires openai + azure-identity SDKs and amplifier_lite error handling."
        )
