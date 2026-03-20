"""GitHub Copilot provider stub — real implementation handled by the Copilot API client."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import ChatRequest, ChatResponse, provider

__all__ = ["GitHubCopilotProvider"]


@provider
class GitHubCopilotProvider:
    """Stub for the GitHub Copilot provider. Use the real Copilot API integration."""

    name = "github_copilot"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Not implemented — use the real GitHub Copilot provider implementation."""
        raise NotImplementedError(
            "GitHubCopilotProvider.complete() is not implemented. "
            "Use the real GitHub Copilot API integration."
        )
