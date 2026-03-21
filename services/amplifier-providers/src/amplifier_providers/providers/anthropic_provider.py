"""Anthropic provider — message conversion and API integration.

Implements _convert_messages() to translate Amplifier's internal Message
representation into the format required by Anthropic's Messages API.
complete() is a placeholder; full streaming implementation is in Task 4.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass
from typing import Any

from amplifier_ipc_protocol import ChatRequest, ChatResponse, provider
from amplifier_ipc_protocol.models import (
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolCallBlock,
    ToolSpec,
    Usage,
)

__all__ = ["AnthropicProvider"]

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 16384


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Minimal LLM provider error with retry metadata."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after = retry_after


def _translate_anthropic_error(error: Exception) -> dict[str, Any]:
    """Translate an Anthropic SDK exception into a dict of error metadata.

    Returns a dict with keys: message, retryable, status_code, retry_after.
    """
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        return {
            "message": str(error),
            "retryable": True,
            "status_code": None,
            "retry_after": None,
        }

    message = str(error)
    retry_after: float | None = None

    if isinstance(error, anthropic.RateLimitError):
        ra = getattr(getattr(error, "response", None), "headers", {}).get("retry-after")
        if ra is not None:
            try:
                retry_after = float(ra)
            except (TypeError, ValueError):
                pass
        return {
            "message": message,
            "retryable": True,
            "status_code": 429,
            "retry_after": retry_after,
        }

    if isinstance(error, anthropic.AuthenticationError):
        return {
            "message": message,
            "retryable": False,
            "status_code": 401,
            "retry_after": None,
        }

    if isinstance(error, anthropic.BadRequestError):
        return {
            "message": message,
            "retryable": False,
            "status_code": 400,
            "retry_after": None,
        }

    if isinstance(error, anthropic.APIStatusError):
        sc: int = getattr(error, "status_code", 0)
        retryable = sc >= 500 or sc == 529
        ra = getattr(getattr(error, "response", None), "headers", {}).get("retry-after")
        if ra is not None:
            try:
                retry_after = float(ra)
            except (TypeError, ValueError):
                pass
        return {
            "message": message,
            "retryable": retryable,
            "status_code": sc,
            "retry_after": retry_after,
        }

    # Generic / unknown errors are retryable
    return {
        "message": message,
        "retryable": True,
        "status_code": None,
        "retry_after": None,
    }


async def retry_with_backoff(
    fn: Any,
    max_retries: int = 5,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
) -> Any:
    """Retry an async callable with exponential backoff.

    - ``ProviderError`` with ``retryable=True`` → retry with backoff
    - ``ProviderError`` with ``retryable=False`` → raise immediately
    - Generic exceptions → retried up to ``max_retries``
    """
    attempt = 0
    delay = initial_delay

    while True:
        try:
            return await fn()
        except ProviderError as exc:
            if not exc.retryable:
                raise
            if attempt >= max_retries:
                raise
            wait = exc.retry_after if exc.retry_after is not None else delay
            if jitter:
                wait = wait * (0.5 + random.random())
            wait = min(wait, max_delay)
            if wait > 0:
                await asyncio.sleep(wait)
            delay = min(delay * 2, max_delay)
            attempt += 1
        except Exception:
            if attempt >= max_retries:
                raise
            wait = delay
            if jitter:
                wait = wait * (0.5 + random.random())
            wait = min(wait, max_delay)
            if wait > 0:
                await asyncio.sleep(wait)
            delay = min(delay * 2, max_delay)
            attempt += 1


@dataclass
class _RateLimitState:
    """Tracks rate-limit capacity from Anthropic response headers.

    Updated after every successful API call.  Resets when the provider is created.
    """

    requests_limit: int | None = None
    requests_remaining: int | None = None
    requests_reset: str | None = None
    tokens_limit: int | None = None
    tokens_remaining: int | None = None
    tokens_reset: str | None = None
    retry_after: float | None = None

    async def maybe_throttle(self) -> None:
        """Sleep if retry_after > 0, then clear the value."""
        if self.retry_after and self.retry_after > 0:
            await asyncio.sleep(self.retry_after)
            self.retry_after = None

    def update_from_response(self, response: Any) -> None:
        """Extract rate-limit headers from an Anthropic API response.

        Looks for headers on ``response.http_response``, ``response._response``,
        or directly on ``response`` (whichever is available).
        """
        raw_headers: Any = None
        for attr in ("http_response", "_response", "response"):
            candidate = getattr(response, attr, None)
            if candidate is not None:
                raw_headers = getattr(candidate, "headers", None)
                if raw_headers is not None:
                    break
        if raw_headers is None:
            raw_headers = getattr(response, "headers", None)
        if raw_headers is None:
            return

        def _get(key: str) -> str | None:
            try:
                return raw_headers.get(key)
            except Exception:
                return None

        mapping: list[tuple[str, str, type]] = [
            ("anthropic-ratelimit-requests-limit", "requests_limit", int),
            ("anthropic-ratelimit-requests-remaining", "requests_remaining", int),
            ("anthropic-ratelimit-tokens-limit", "tokens_limit", int),
            ("anthropic-ratelimit-tokens-remaining", "tokens_remaining", int),
            ("retry-after", "retry_after", float),
        ]
        for header, attr, cast in mapping:
            val = _get(header)
            if val is not None:
                try:
                    setattr(self, attr, cast(val))
                except (TypeError, ValueError):
                    pass


@provider
class AnthropicProvider:
    """Anthropic Claude provider with message-format conversion."""

    name = "anthropic"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the provider.

        Args:
            config: Optional configuration dict.  Recognised keys:
                ``api_key``, ``model``, ``max_tokens``, ``temperature``,
                ``thinking_budget``.  Missing keys fall back to environment
                variables or built-in defaults.
        """
        config = config or {}
        self._api_key: str | None = config.get("api_key") or os.environ.get(
            "ANTHROPIC_API_KEY"
        )
        self._client: Any = None  # Lazy-initialised on first .client access
        self.model: str = config.get("model", DEFAULT_MODEL)
        self.max_tokens: int = int(config.get("max_tokens", DEFAULT_MAX_TOKENS))
        self.temperature: float = float(config.get("temperature", 1.0))
        self.thinking_budget: int | None = config.get("thinking_budget")

        # Track tool-call IDs repaired with synthetic results to prevent
        # infinite detection loops across LLM iterations.
        self._repaired_tool_ids: set[str] = set()

        self._rate_limit_state = _RateLimitState()

    @property
    def client(self) -> Any:
        """Lazily initialise and return the ``anthropic.AsyncAnthropic`` client."""
        if self._client is None:
            try:
                import anthropic  # type: ignore[import-untyped]  # noqa: PLC0415
            except ImportError as exc:
                raise ImportError(
                    "The 'anthropic' package is required.  "
                    "Install it with: pip install anthropic"
                ) from exc
            if self._api_key is None:
                raise ValueError(
                    "An Anthropic API key is required.  "
                    "Pass api_key in config or set ANTHROPIC_API_KEY."
                )
            self._client = anthropic.AsyncAnthropic(
                api_key=self._api_key,
                max_retries=0,
            )
        return self._client

    # ------------------------------------------------------------------
    # Message conversion — Amplifier → Anthropic Messages API
    # ------------------------------------------------------------------

    def _convert_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Convert an Amplifier Message list to Anthropic Messages API format.

        Batches consecutive tool-result messages into a single user message
        (Anthropic requires all tool_result blocks from one assistant turn to
        arrive in a single user-role message).

        System messages are silently skipped — they are passed separately as
        the ``system`` parameter of the API call.
        """
        result: list[dict[str, Any]] = []
        i = 0

        # A `while` loop (rather than `for`) is used because the tool-result
        # branch needs to consume multiple messages in a single iteration
        # (batching consecutive tool messages).  All other branches are simple
        # single-step increments — they just use `i += 1; continue` to keep
        # the structure consistent.
        while i < len(messages):
            msg = messages[i]
            role: str = getattr(msg, "role", "") or (
                msg.get("role", "") if isinstance(msg, dict) else ""
            )

            if role == "system":
                # Handled separately as the Anthropic `system` parameter.
                i += 1
                continue

            if role == "tool":
                # Batch all consecutive tool-result messages into ONE user message.
                tool_results: list[dict[str, Any]] = []
                while i < len(messages):
                    cur = messages[i]
                    cur_role = getattr(cur, "role", "") or (
                        cur.get("role", "") if isinstance(cur, dict) else ""
                    )
                    if cur_role != "tool":
                        break
                    tool_call_id: str | None = getattr(cur, "tool_call_id", None) or (
                        cur.get("tool_call_id") if isinstance(cur, dict) else None
                    )
                    tool_content: Any = getattr(cur, "content", "") or (
                        cur.get("content", "") if isinstance(cur, dict) else ""
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_call_id or "",
                            "content": tool_content or "",
                        }
                    )
                    i += 1

                if tool_results:
                    result.append({"role": "user", "content": tool_results})
                continue  # `i` already advanced inside the inner while

            if role == "assistant":
                content_blocks = self._convert_assistant_content(msg)
                result.append({"role": "assistant", "content": content_blocks})
                i += 1
                continue

            if role == "developer":
                raw_content: str = ""
                raw = getattr(msg, "content", None) or (
                    msg.get("content") if isinstance(msg, dict) else None
                )
                if isinstance(raw, str):
                    raw_content = raw
                elif raw is not None:
                    logger.warning(
                        "Developer message has non-string content type %s — converting to empty string",
                        type(raw).__name__,
                    )
                wrapped = f"<context_file>\n{raw_content}\n</context_file>"
                result.append({"role": "user", "content": wrapped})
                i += 1
                continue

            if role == "user":
                user_content = getattr(msg, "content", None) or (
                    msg.get("content") if isinstance(msg, dict) else None
                )
                if isinstance(user_content, list):
                    # Structured content blocks (text, image, …)
                    blocks: list[dict[str, Any]] = []
                    for block in user_content:
                        if isinstance(block, dict):
                            btype = block.get("type")
                            if btype == "text":
                                blocks.append(
                                    {"type": "text", "text": block.get("text", "")}
                                )
                            elif btype == "image":
                                source = block.get("source", {})
                                if source.get("type") == "base64":
                                    blocks.append(
                                        {
                                            "type": "image",
                                            "source": {
                                                "type": "base64",
                                                "media_type": source.get(
                                                    "media_type", "image/jpeg"
                                                ),
                                                "data": source.get("data"),
                                            },
                                        }
                                    )
                                else:
                                    logger.warning(
                                        "Unsupported image source type: %s",
                                        source.get("type"),
                                    )
                        else:
                            # Pydantic model block
                            btype = getattr(block, "type", None)
                            if btype == "text":
                                blocks.append(
                                    {
                                        "type": "text",
                                        "text": getattr(block, "text", ""),
                                    }
                                )
                    if blocks:
                        result.append({"role": "user", "content": blocks})
                    else:
                        logger.warning(
                            "User message had a content list but no recognised blocks — skipping"
                        )
                else:
                    result.append({"role": "user", "content": user_content or ""})
                i += 1
                continue

            # Unknown role — log and skip
            logger.warning("Unknown message role %r — skipping", role)
            i += 1

        return result

    def _convert_assistant_content(self, msg: Any) -> list[dict[str, Any]]:
        """Convert an assistant Message's content to Anthropic content blocks.

        Handles:
        * Plain string content
        * TextBlock, ThinkingBlock, ToolCallBlock (Pydantic models)
        * tool_calls field (from context storage serialisation)
        * Dict-based blocks

        Always returns at least one block (Anthropic rejects empty content arrays).
        """
        content: Any = getattr(msg, "content", None) or (
            msg.get("content") if isinstance(msg, dict) else None
        )
        tool_calls: Any = getattr(msg, "tool_calls", None) or (
            msg.get("tool_calls") if isinstance(msg, dict) else None
        )

        blocks: list[dict[str, Any]] = []

        # --- Convert content field ---
        if isinstance(content, str):
            if content:
                blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, ThinkingBlock):
                    tb: dict[str, Any] = {
                        "type": "thinking",
                        "thinking": item.thinking,
                    }
                    if item.signature is not None:
                        tb["signature"] = item.signature
                    blocks.append(tb)
                elif isinstance(item, ToolCallBlock):
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": item.id,
                            "name": item.name,
                            "input": item.input,
                        }
                    )
                elif isinstance(item, TextBlock):
                    if item.text:
                        blocks.append({"type": "text", "text": item.text})
                elif isinstance(item, dict):
                    btype = item.get("type")
                    if btype == "thinking":
                        tb = {"type": "thinking", "thinking": item.get("thinking", "")}
                        if "signature" in item:
                            tb["signature"] = item["signature"]
                        blocks.append(tb)
                    elif btype in ("tool_use", "tool_call"):
                        blocks.append(
                            {
                                "type": "tool_use",
                                "id": item.get("id", ""),
                                "name": item.get("name", ""),
                                "input": item.get("input", {}),
                            }
                        )
                    elif btype == "text":
                        text = item.get("text", "")
                        if text:
                            blocks.append({"type": "text", "text": text})
                    else:
                        # Pass unknown block types through (strip provider-internal fields)
                        cleaned = {k: v for k, v in item.items() if k != "visibility"}
                        if cleaned:
                            blocks.append(cleaned)
                else:
                    # Other Pydantic-like objects
                    btype = getattr(item, "type", None)
                    if btype == "thinking":
                        tb = {
                            "type": "thinking",
                            "thinking": getattr(item, "thinking", ""),
                        }
                        sig = getattr(item, "signature", None)
                        if sig is not None:
                            tb["signature"] = sig
                        blocks.append(tb)
                    elif btype in ("tool_use", "tool_call"):
                        blocks.append(
                            {
                                "type": "tool_use",
                                "id": getattr(item, "id", ""),
                                "name": getattr(item, "name", ""),
                                "input": getattr(item, "input", {}),
                            }
                        )
                    elif btype == "text":
                        text = getattr(item, "text", "")
                        if text:
                            blocks.append({"type": "text", "text": text})

        # --- Convert tool_calls field (context-storage serialisation) ---
        if tool_calls:
            for tc in tool_calls:
                if isinstance(tc, dict):
                    tc_id = tc.get("id", "")
                    tc_name = tc.get("name") or tc.get("tool", "")
                    tc_input = tc.get("arguments") or tc.get("input", {})
                else:
                    tc_id = getattr(tc, "id", "")
                    tc_name = getattr(tc, "name", "") or getattr(tc, "tool", "")
                    tc_input = getattr(tc, "arguments", None) or getattr(
                        tc, "input", {}
                    )
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc_id,
                        "name": tc_name,
                        "input": tc_input or {},
                    }
                )

        # Anthropic requires at least one content block
        if not blocks:
            blocks.append({"type": "text", "text": ""})

        return blocks

    def _convert_tools_from_request(
        self, tools: list[ToolSpec]
    ) -> list[dict[str, Any]]:
        """Convert Amplifier ToolSpec objects to Anthropic tool format.

        Each tool becomes::

            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.parameters,
            }

        An empty tool list returns an empty list.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.parameters if tool.parameters is not None else {},
            }
            for tool in tools
        ]

    def _convert_to_chat_response(self, response: Any) -> ChatResponse:
        """Convert an Anthropic Messages API response to ChatResponse.

        * ``text`` blocks         → :class:`TextBlock`
        * ``thinking`` blocks     → :class:`ThinkingBlock`
        * ``tool_use`` blocks     → :class:`ToolCallBlock` in ``content_blocks``
                                    **and** :class:`ToolCall` in ``tool_calls``

        Usage extraction
        ----------------
        ``total_tokens`` is computed as ``input_tokens + output_tokens``.
        ``cache_read_tokens`` / ``cache_write_tokens`` are ``None`` when zero.
        """
        content_blocks: list[Any] = []
        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []

        for block in response.content or []:
            block_type: str | None = getattr(block, "type", None)

            if block_type == "text":
                text = getattr(block, "text", "")
                content_blocks.append(TextBlock(text=text))
                if text:
                    text_parts.append(text)

            elif block_type == "thinking":
                thinking = getattr(block, "thinking", "")
                signature = getattr(block, "signature", None)
                content_blocks.append(
                    ThinkingBlock(thinking=thinking, signature=signature)
                )

            elif block_type == "tool_use":
                tool_id = getattr(block, "id", "")
                tool_name = getattr(block, "name", "")
                tool_input: dict[str, Any] = getattr(block, "input", {}) or {}
                content_blocks.append(
                    ToolCallBlock(id=tool_id, name=tool_name, input=tool_input)
                )
                tool_calls.append(
                    ToolCall(id=tool_id, name=tool_name, arguments=tool_input)
                )

        # --- Usage extraction ---
        usage_obj = response.usage
        input_tokens: int = getattr(usage_obj, "input_tokens", 0)
        output_tokens: int = getattr(usage_obj, "output_tokens", 0)
        raw_cache_read: int = getattr(usage_obj, "cache_read_input_tokens", 0)
        raw_cache_write: int = getattr(usage_obj, "cache_creation_input_tokens", 0)

        usage = Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cache_read_tokens=raw_cache_read if raw_cache_read else None,
            cache_write_tokens=raw_cache_write if raw_cache_write else None,
        )

        combined_text = "\n\n".join(text_parts) or None

        return ChatResponse(
            content_blocks=content_blocks,
            content=content_blocks,  # content mirrors content_blocks for backward compat
            text=combined_text,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
            finish_reason=getattr(response, "stop_reason", None),
            metadata={"model": getattr(response, "model", None)},
        )

    # ------------------------------------------------------------------
    # Tool-result repair helpers
    # ------------------------------------------------------------------

    def _find_missing_tool_results(
        self, messages: list[Any]
    ) -> list[tuple[int, str, str, dict]]:
        """Scan messages for assistant tool_call blocks without matching tool results.

        Returns a list of ``(msg_idx, call_id, tool_name, tool_input)`` tuples
        for every tool call that lacks a corresponding tool-result message.
        Call IDs already in ``self._repaired_tool_ids`` are excluded to prevent
        infinite repair loops.
        """
        # Collect all tool-result IDs that are already present.
        result_ids: set[str] = set()
        for msg in messages:
            role: str = getattr(msg, "role", "") or (
                msg.get("role", "") if isinstance(msg, dict) else ""
            )
            if role == "tool":
                tcid: str | None = getattr(msg, "tool_call_id", None) or (
                    msg.get("tool_call_id") if isinstance(msg, dict) else None
                )
                if tcid:
                    result_ids.add(tcid)

        missing: list[tuple[int, str, str, dict]] = []

        for idx, msg in enumerate(messages):
            role = getattr(msg, "role", "") or (
                msg.get("role", "") if isinstance(msg, dict) else ""
            )
            if role != "assistant":
                continue

            content: Any = getattr(msg, "content", None) or (
                msg.get("content") if isinstance(msg, dict) else None
            )
            tool_calls_field: Any = getattr(msg, "tool_calls", None) or (
                msg.get("tool_calls") if isinstance(msg, dict) else None
            )

            # Check content list for ToolCallBlock / dict tool_use items.
            if isinstance(content, list):
                for block in content:
                    call_id: str = ""
                    tool_name: str = ""
                    tool_input: dict = {}

                    if hasattr(block, "type") and getattr(block, "type", None) in (
                        "tool_call",
                        "tool_use",
                    ):
                        call_id = getattr(block, "id", "")
                        tool_name = getattr(block, "name", "")
                        tool_input = getattr(block, "input", {}) or {}
                    elif isinstance(block, dict) and block.get("type") in (
                        "tool_use",
                        "tool_call",
                    ):
                        call_id = block.get("id", "")
                        tool_name = block.get("name", "")
                        tool_input = block.get("input", {}) or {}
                    else:
                        continue

                    if (
                        call_id
                        and call_id not in result_ids
                        and call_id not in self._repaired_tool_ids
                    ):
                        missing.append((idx, call_id, tool_name, tool_input))

            # Check the tool_calls field (context-storage serialisation).
            if tool_calls_field:
                for tc in tool_calls_field:
                    if isinstance(tc, dict):
                        call_id = tc.get("id", "")
                        tool_name = tc.get("name") or tc.get("tool", "")
                        tool_input = tc.get("arguments") or tc.get("input") or {}
                    else:
                        call_id = getattr(tc, "id", "")
                        tool_name = getattr(tc, "name", "") or getattr(tc, "tool", "")
                        tool_input = (
                            getattr(tc, "arguments", None) or getattr(tc, "input", {})
                        ) or {}

                    if (
                        call_id
                        and call_id not in result_ids
                        and call_id not in self._repaired_tool_ids
                    ):
                        missing.append((idx, call_id, tool_name, tool_input))

        return missing

    def _create_synthetic_result(self, call_id: str, tool_name: str) -> Any:
        """Create a synthetic error tool-result Message for a missing tool call.

        The content contains a structured error explaining what happened and
        instructing the model to retry.
        """
        from amplifier_ipc_protocol import Message  # noqa: PLC0415

        content = (
            f"[SYSTEM ERROR: Tool result missing from conversation history] "
            f"Tool '{tool_name}' (call_id={call_id}) did not return a result. "
            f"Please retry the tool call."
        )
        return Message(role="tool", content=content, tool_call_id=call_id)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Call the Anthropic Messages API and return a ChatResponse.

        Orchestrates: tool-result repair → message separation → system block
        construction → API call with retry → response conversion.
        """
        from collections import defaultdict  # noqa: PLC0415

        messages: list[Any] = list(request.messages)

        # 1. REPAIR: inject synthetic tool results for any missing tool calls.
        missing = self._find_missing_tool_results(messages)
        if missing:
            grouped: dict[int, list[tuple[int, str, str, dict]]] = defaultdict(list)
            for item in missing:
                grouped[item[0]].append(item)
                self._repaired_tool_ids.add(item[1])

            offset = 0
            for msg_idx in sorted(grouped.keys()):
                insert_pos = msg_idx + 1 + offset
                for _, call_id, tool_name, _ in grouped[msg_idx]:
                    synthetic = self._create_synthetic_result(call_id, tool_name)
                    messages.insert(insert_pos, synthetic)
                    insert_pos += 1
                    offset += 1

        # 2. Separate system messages from the conversation.
        def _role(m: Any) -> str:
            return getattr(m, "role", "") or (
                m.get("role", "") if isinstance(m, dict) else ""
            )

        system_msgs = [m for m in messages if _role(m) == "system"]
        conversation = [m for m in messages if _role(m) != "system"]

        # 3. Build system parameter with cache_control for prompt caching.
        system_blocks: list[dict[str, Any]] = []
        if request.system:
            system_blocks.append(
                {
                    "type": "text",
                    "text": request.system,
                    "cache_control": {"type": "ephemeral"},
                }
            )
        elif system_msgs:
            for smsg in system_msgs:
                text: str = (
                    getattr(smsg, "content", "")
                    or (smsg.get("content", "") if isinstance(smsg, dict) else "")
                    or ""
                )
                if text:
                    system_blocks.append(
                        {
                            "type": "text",
                            "text": text,
                            "cache_control": {"type": "ephemeral"},
                        }
                    )

        # 4. Convert messages to Anthropic wire format.
        api_messages = self._convert_messages(conversation)

        # 5. Build core API parameters.
        model: str = kwargs.get("model", self.model)
        max_tokens_val: int = int(
            request.max_output_tokens or kwargs.get("max_tokens") or self.max_tokens
        )
        api_params: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens_val,
        }

        # 6. Add system param if present.
        if system_blocks:
            api_params["system"] = system_blocks

        # 7. Temperature: request field takes priority over config.
        api_params["temperature"] = (
            request.temperature if request.temperature is not None else self.temperature
        )

        # 8. Tools.
        if request.tools:
            api_params["tools"] = self._convert_tools_from_request(request.tools)

        # 9. Extended thinking.
        thinking_budget: int | None = (
            kwargs.get("thinking_budget") or self.thinking_budget
        )
        if thinking_budget:
            api_params["thinking"] = {
                "type": "enabled",
                "budget_tokens": int(thinking_budget),
            }
            min_max = int(thinking_budget) + 1024
            if api_params["max_tokens"] < min_max:
                api_params["max_tokens"] = min_max

        # 10. Pre-emptive rate-limit throttle.
        await self._rate_limit_state.maybe_throttle()

        # 11. API call wrapped in retry_with_backoff.
        async def _call() -> Any:
            try:
                return await self.client.messages.create(**api_params)
            except Exception as exc:
                meta = _translate_anthropic_error(exc)
                raise ProviderError(
                    meta["message"],
                    retryable=meta["retryable"],
                    status_code=meta["status_code"],
                    retry_after=meta["retry_after"],
                ) from exc

        response = await retry_with_backoff(_call)

        # 12. Update rate-limit state from response headers.
        self._rate_limit_state.update_from_response(response)

        # 13. Convert and return.
        return self._convert_to_chat_response(response)
