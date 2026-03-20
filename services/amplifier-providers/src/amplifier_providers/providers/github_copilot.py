"""GitHub Copilot provider stub — requires SDK and amplifier_lite internals not yet ported."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import provider, ChatRequest, ChatResponse, TextBlock, Usage


@provider
class GitHubCopilotProvider:
    """GitHub Copilot provider (stub — not yet implemented in IPC service)."""

    name = "github_copilot"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        raise NotImplementedError(
            "GitHubCopilotProvider stub: not yet implemented in IPC service. "
            "Requires github-copilot-sdk and amplifier_lite error handling."
        )
