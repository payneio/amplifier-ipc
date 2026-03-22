"""Azure OpenAI provider — uses Azure-specific authentication and endpoint configuration.

Inherits from OpenAIProvider to reuse message/tool/response conversion methods.
Uses ``openai.AsyncAzureOpenAI`` client with API key or Azure AD token auth.
"""

from __future__ import annotations

import os
from typing import Any

from amplifier_ipc_protocol import ChatRequest, ChatResponse, provider

from amplifier_providers.providers.openai_provider import OpenAIProvider

__all__ = ["AzureOpenAIProvider"]

DEFAULT_API_VERSION = "2024-02-01"


@provider
class AzureOpenAIProvider(OpenAIProvider):
    """Azure OpenAI provider with Azure-specific auth and endpoint configuration.

    Inherits all message, tool, and response conversion methods from OpenAIProvider.
    Overrides client initialisation to use ``openai.AsyncAzureOpenAI``.
    """

    name = "azure_openai"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the Azure OpenAI provider.

        Args:
            config: Optional configuration dict.  Recognised keys:
                ``api_key``         — Azure OpenAI API key (falls back to AZURE_OPENAI_API_KEY)
                ``azure_endpoint``  — Azure resource endpoint URL (falls back to AZURE_OPENAI_ENDPOINT)
                ``api_version``     — Azure API version (falls back to AZURE_OPENAI_API_VERSION)
                ``model``, ``max_tokens``, ``temperature`` — forwarded to OpenAIProvider
        """
        config = config or {}

        # Azure-specific fields — read before calling super().__init__() so
        # we can pass a neutral config dict to the parent.
        self._azure_endpoint: str | None = config.get(
            "azure_endpoint"
        ) or os.environ.get("AZURE_OPENAI_ENDPOINT")
        self._api_version: str = (
            config.get("api_version")
            or os.environ.get("AZURE_OPENAI_API_VERSION")
            or DEFAULT_API_VERSION
        )

        # Build a config dict for the parent that uses the Azure key env var
        parent_config = dict(config)
        if not parent_config.get("api_key"):
            azure_key = os.environ.get("AZURE_OPENAI_API_KEY")
            if azure_key:
                parent_config["api_key"] = azure_key

        super().__init__(config=parent_config)

        # Override the parent's _api_key resolution to also check AZURE_OPENAI_API_KEY
        if self._api_key is None:
            self._api_key = os.environ.get("AZURE_OPENAI_API_KEY")

    @property
    def client(self) -> Any:
        """Lazily initialise and return the ``openai.AsyncAzureOpenAI`` client.

        Falls back to DefaultAzureCredential (azure-identity) when no API key
        is configured.
        """
        if self._client is None:
            try:
                import openai  # type: ignore[import-untyped]  # noqa: PLC0415
            except ImportError as exc:
                raise ImportError(
                    "The 'openai' package is required.  "
                    "Install it with: pip install openai"
                ) from exc

            if self._api_key is not None:
                # API key auth
                self._client = openai.AsyncAzureOpenAI(
                    api_key=self._api_key,
                    azure_endpoint=self._azure_endpoint or "",
                    api_version=self._api_version,
                    max_retries=0,
                )
            else:
                # Azure AD token auth via azure-identity
                try:
                    from azure.identity import (
                        DefaultAzureCredential,
                        get_bearer_token_provider,
                    )  # type: ignore[import-untyped]  # noqa: PLC0415
                except ImportError as exc:
                    raise ValueError(
                        "An Azure OpenAI API key is required, or install 'azure-identity' "
                        "for token-based auth.  "
                        "Set AZURE_OPENAI_API_KEY or pip install azure-identity."
                    ) from exc

                token_provider = get_bearer_token_provider(
                    DefaultAzureCredential(),
                    "https://cognitiveservices.azure.com/.default",
                )
                self._client = openai.AsyncAzureOpenAI(
                    azure_ad_token_provider=token_provider,
                    azure_endpoint=self._azure_endpoint or "",
                    api_version=self._api_version,
                    max_retries=0,
                )
        return self._client

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Call the Azure OpenAI Chat Completions API and return a ChatResponse.

        Delegates to the parent OpenAIProvider.complete() which uses self.client
        (overridden here to return an AsyncAzureOpenAI instance).
        """
        return await super().complete(request, **kwargs)
