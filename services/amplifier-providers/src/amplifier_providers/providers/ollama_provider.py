"""Ollama provider — local model support via the ollama Python SDK.

Connects to a local Ollama server (default http://localhost:11434).
No rate limiting, no auth tokens. Tool support depends on model capability.
Token tracking is optional — some models don't report tokens.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from amplifier_ipc.protocol import ChatRequest, ChatResponse, provider
from amplifier_ipc.protocol.models import (
    TextBlock,
    ToolCall,
    ToolCallBlock,
    ToolSpec,
    Usage,
)

__all__ = ["OllamaProvider"]

logger = logging.getLogger(__name__)

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1"


@provider
class OllamaProvider:
    """Ollama provider for local model support via the ollama Python SDK."""

    name = "ollama"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the provider.

        Args:
            config: Optional configuration dict. Recognised keys:
                ``host``, ``model``. Missing keys fall back to environment
                variables or built-in defaults.

                - ``host``: Ollama server URL. Falls back to ``OLLAMA_HOST``
                  env var, then ``http://localhost:11434``.
                - ``model``: Model name. Defaults to ``llama3.1``.
        """
        config = config or {}
        self.host: str = (
            config.get("host") or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST
        )
        self.model: str = config.get("model", DEFAULT_MODEL)
        self._client: Any = None  # Lazy-initialised on first .client access

    @property
    def client(self) -> Any:
        """Lazily initialise and return the ``ollama.AsyncClient``."""
        if self._client is None:
            try:
                import ollama  # type: ignore[import-untyped]  # noqa: PLC0415
            except ImportError as exc:
                raise ImportError(
                    "The 'ollama' package is required.  "
                    "Install it with: pip install ollama"
                ) from exc
            self._client = ollama.AsyncClient(host=self.host)
        return self._client

    # ------------------------------------------------------------------
    # Message conversion — Amplifier → Ollama format
    # ------------------------------------------------------------------

    def _convert_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Convert an Amplifier Message list to Ollama chat format.

        Ollama uses the same role/content format as OpenAI:
        ``{"role": "user" | "assistant" | "system" | "tool", "content": "..."}``.
        """
        result: list[dict[str, Any]] = []

        for msg in messages:
            role: str = getattr(msg, "role", "") or (
                msg.get("role", "") if isinstance(msg, dict) else ""
            )
            content: Any = getattr(msg, "content", None) or (
                msg.get("content") if isinstance(msg, dict) else None
            )

            if role in ("system", "user", "assistant"):
                # Simple string content — pass through directly
                if isinstance(content, str):
                    result.append({"role": role, "content": content})
                elif isinstance(content, list):
                    # Flatten list content to text
                    parts: list[str] = []
                    for item in content:
                        if isinstance(item, TextBlock):
                            if item.text:
                                parts.append(item.text)
                        elif isinstance(item, str):
                            parts.append(item)
                        else:
                            text = getattr(item, "text", None)
                            if text:
                                parts.append(text)
                    result.append({"role": role, "content": "\n\n".join(parts)})
                else:
                    result.append({"role": role, "content": content or ""})
                continue

            if role == "tool":
                tool_call_id: str | None = getattr(msg, "tool_call_id", None) or (
                    msg.get("tool_call_id") if isinstance(msg, dict) else None
                )
                tool_content: str = (
                    content if isinstance(content, str) else str(content or "")
                )
                result.append(
                    {
                        "role": "tool",
                        "content": tool_content,
                        "tool_call_id": tool_call_id or "",
                    }
                )
                continue

            # Unknown role — log and skip
            logger.warning("Unknown message role %r — skipping", role)

        return result

    def _convert_tools_from_request(
        self, tools: list[ToolSpec]
    ) -> list[dict[str, Any]]:
        """Convert Amplifier ToolSpec objects to Ollama tool format.

        Ollama uses the same OpenAI-compatible function format::

            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.parameters,
                },
            }

        An empty tool list returns an empty list.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.parameters
                    if tool.parameters is not None
                    else {},
                },
            }
            for tool in tools
        ]

    def _convert_to_chat_response(self, response: dict[str, Any]) -> ChatResponse:
        """Convert an Ollama dict response to ChatResponse.

        Ollama returns dicts (not objects). Structure::

            {
                "message": {"role": "assistant", "content": "...", "tool_calls": [...]},
                "done": True,
                "eval_count": 42,           # output tokens
                "prompt_eval_count": 10,    # input tokens
            }

        Token counts:
        - ``eval_count``        → ``output_tokens``
        - ``prompt_eval_count`` → ``input_tokens``
        """
        content_blocks: list[Any] = []
        tool_calls: list[ToolCall] = []

        message = response.get("message", {})
        text_content: str | None = message.get("content") if message else None
        raw_tool_calls: list[Any] | None = (
            message.get("tool_calls") if message else None
        )

        if text_content:
            content_blocks.append(TextBlock(text=text_content))

        if raw_tool_calls:
            for tc in raw_tool_calls:
                # Ollama tool call format (OpenAI-compatible):
                # {"function": {"name": "...", "arguments": {...}}}
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                tool_name: str = fn.get("name", "") if fn else ""
                raw_args: Any = fn.get("arguments", {}) if fn else {}

                # Arguments may be a dict already or a JSON string
                if isinstance(raw_args, str):
                    try:
                        tool_input: dict[str, Any] = json.loads(raw_args)
                    except (json.JSONDecodeError, TypeError):
                        tool_input = {}
                elif isinstance(raw_args, dict):
                    tool_input = raw_args
                else:
                    tool_input = {}

                # Ollama doesn't always provide a tool call ID — generate one
                tool_id: str = tc.get("id", "") if isinstance(tc, dict) else ""

                content_blocks.append(
                    ToolCallBlock(id=tool_id, name=tool_name, input=tool_input)
                )
                tool_calls.append(
                    ToolCall(id=tool_id, name=tool_name, arguments=tool_input)
                )

        # --- Usage extraction ---
        # Some models don't report tokens — default to 0
        output_tokens: int = response.get("eval_count") or 0
        input_tokens: int = response.get("prompt_eval_count") or 0

        usage = Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

        # Extract combined text
        text_blocks = [b for b in content_blocks if isinstance(b, TextBlock)]
        combined_text = "\n\n".join(b.text for b in text_blocks if b.text) or None

        return ChatResponse(
            content_blocks=content_blocks,
            content=content_blocks,
            text=combined_text,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
            finish_reason="stop" if response.get("done") else None,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Call the Ollama chat API and return a ChatResponse.

        Builds the message list, converts tools if provided, and calls
        ``client.chat()``.
        """
        messages_list: list[Any] = list(request.messages)
        api_messages = self._convert_messages(messages_list)

        model: str = kwargs.get("model", self.model)
        api_params: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
        }

        # Tools (only if request has tools)
        if request.tools:
            api_params["tools"] = self._convert_tools_from_request(request.tools)

        # API call
        try:
            response = await self.client.chat(**api_params)
        except Exception as exc:
            exc_str = str(exc)
            # Connection errors and model-not-found are both surfaced as-is
            raise RuntimeError(f"Ollama API call failed: {exc_str}") from exc

        return self._convert_to_chat_response(response)
