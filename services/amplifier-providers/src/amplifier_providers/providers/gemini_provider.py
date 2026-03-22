"""Gemini provider — Google Generative AI SDK integration for amplifier-providers IPC service.

Provides GeminiProvider with: message and tool conversion (Amplifier ↔ Gemini
Content/Part formats), complete() with thinking_budget support, synthetic tool
call ID generation (Gemini API does not return tool call IDs), and error handling.
Uses `model.generate_content_async()`.
"""

from __future__ import annotations

import logging
import os
import uuid
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

__all__ = ["GeminiProvider"]

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.0-flash"
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


@provider
class GeminiProvider:
    """Gemini provider with message-format conversion using google-generativeai SDK.

    Key differences from OpenAI/Anthropic:
    - Synthetic tool call IDs — Gemini API does not return tool call IDs
    - thinking_budget parameter — Gemini supports a thinking budget for reasoning
    - Different message format — Gemini uses Content objects with parts
    - System messages extracted separately as system_instruction
    """

    name = "gemini"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the provider.

        Args:
            config: Optional configuration dict. Recognised keys:
                ``api_key``, ``model``, ``max_tokens``, ``temperature``,
                ``thinking_budget``. Missing keys fall back to environment
                variables or built-in defaults.
        """
        config = config or {}
        self._api_key: str | None = config.get("api_key") or os.environ.get(
            "GOOGLE_API_KEY"
        )
        self._model: Any = None  # Lazy-initialised on first ._get_model() call
        self.model: str = config.get("model", DEFAULT_MODEL)
        self.max_tokens: int = int(config.get("max_tokens", DEFAULT_MAX_TOKENS))
        self.temperature: float = float(config.get("temperature", 1.0))
        self.thinking_budget: int | None = config.get("thinking_budget")

    def _get_model(self, **kwargs: Any) -> Any:
        """Lazily initialise and return the Gemini GenerativeModel."""
        if self._model is None:
            try:
                import google.generativeai as genai  # type: ignore[import-untyped]  # noqa: PLC0415
            except ImportError as exc:
                raise ImportError(
                    "The 'google-generativeai' package is required.  "
                    "Install it with: pip install google-generativeai"
                ) from exc
            if self._api_key:
                genai.configure(api_key=self._api_key)
            self._model = genai.GenerativeModel(model_name=self.model)
        return self._model

    # ------------------------------------------------------------------
    # Message conversion — Amplifier → Gemini Content/Part API
    # ------------------------------------------------------------------

    def _convert_messages(
        self, messages: list[Any]
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Convert an Amplifier Message list to Gemini Content format.

        Returns:
            A tuple of (contents, system_instruction) where:
            - contents: list of dicts with "role" and "parts" for conversation
            - system_instruction: extracted system message text, or None

        Notes:
            - System messages are extracted and returned as system_instruction
            - User messages → role="user"
            - Assistant messages → role="model"
            - Tool result messages → function_response parts in role="user" Content
        """
        try:
            from google.generativeai import protos  # type: ignore[import-untyped]  # noqa: PLC0415
        except ImportError:
            protos = None  # type: ignore[assignment]

        contents: list[dict[str, Any]] = []
        system_parts: list[str] = []

        for msg in messages:
            role: str = getattr(msg, "role", "") or (
                msg.get("role", "") if isinstance(msg, dict) else ""
            )
            content: Any = getattr(msg, "content", None) or (
                msg.get("content") if isinstance(msg, dict) else None
            )

            if role == "system":
                # Extract system messages for system_instruction
                if isinstance(content, str):
                    system_parts.append(content)
                continue

            if role == "tool":
                # Tool result → function_response part in user Content
                tool_call_id: str | None = getattr(msg, "tool_call_id", None) or (
                    msg.get("tool_call_id") if isinstance(msg, dict) else None
                )
                result_text: str = ""
                if isinstance(content, str):
                    result_text = content

                if protos is not None:
                    fn_response = protos.FunctionResponse(
                        name=tool_call_id or "unknown",
                        response={"result": result_text},
                    )
                    part = protos.Part(function_response=fn_response)
                else:
                    # Fallback dict representation for tests without SDK
                    part = {
                        "function_response": {
                            "name": tool_call_id or "unknown",
                            "response": {"result": result_text},
                        }
                    }
                contents.append({"role": "user", "parts": [part]})
                continue

            if role == "assistant":
                parts = self._convert_assistant_parts(msg, protos)
                contents.append({"role": "model", "parts": parts})
                continue

            if role in ("user", "developer"):
                # User message — may have string or list content
                parts = self._convert_user_parts(content, protos)
                contents.append({"role": "user", "parts": parts})
                continue

            # Unknown role — log and skip
            logger.warning("Unknown message role %r — skipping", role)

        system_instruction: str | None = (
            "\n\n".join(system_parts) if system_parts else None
        )
        return contents, system_instruction

    def _convert_user_parts(self, content: Any, protos: Any) -> list[Any]:
        """Convert user message content to Gemini Part objects."""
        if isinstance(content, str):
            if protos is not None:
                return [protos.Part(text=content)]
            return [{"text": content}]

        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, TextBlock):
                    if protos is not None:
                        parts.append(protos.Part(text=item.text or ""))
                    else:
                        parts.append({"text": item.text or ""})
                elif isinstance(item, str):
                    if protos is not None:
                        parts.append(protos.Part(text=item))
                    else:
                        parts.append({"text": item})
            return parts

        # Fallback for string-like content
        text = str(content) if content is not None else ""
        if protos is not None:
            return [protos.Part(text=text)]
        return [{"text": text}]

    def _convert_assistant_parts(self, msg: Any, protos: Any) -> list[Any]:
        """Convert assistant message content to Gemini Part objects."""
        content: Any = getattr(msg, "content", None) or (
            msg.get("content") if isinstance(msg, dict) else None
        )
        parts: list[Any] = []

        if isinstance(content, str):
            if protos is not None:
                parts.append(protos.Part(text=content))
            else:
                parts.append({"text": content})
            return parts

        if isinstance(content, list):
            for item in content:
                if isinstance(item, TextBlock):
                    if protos is not None:
                        parts.append(protos.Part(text=item.text or ""))
                    else:
                        parts.append({"text": item.text or ""})
                elif isinstance(item, ToolCallBlock):
                    # Convert tool call back to function_call part
                    try:
                        fn_args = item.input or {}
                    except AttributeError:
                        fn_args = {}
                    if protos is not None:
                        fc = protos.FunctionCall(name=item.name, args=fn_args)
                        parts.append(protos.Part(function_call=fc))
                    else:
                        parts.append(
                            {"function_call": {"name": item.name, "args": fn_args}}
                        )
                elif isinstance(item, ThinkingBlock):
                    # Thinking blocks — skip in output (Gemini doesn't support round-tripping)
                    pass
                elif isinstance(item, str):
                    if protos is not None:
                        parts.append(protos.Part(text=item))
                    else:
                        parts.append({"text": item})

        return parts

    def _convert_tools_from_request(self, tools: list[ToolSpec]) -> list[Any]:
        """Convert Amplifier ToolSpec objects to Gemini FunctionDeclaration format.

        Each tool becomes a FunctionDeclaration with name, description, and parameters.
        An empty tool list returns an empty list.
        """
        if not tools:
            return []

        try:
            from google.generativeai import protos  # type: ignore[import-untyped]  # noqa: PLC0415

            declarations = []
            for tool in tools:
                params = tool.parameters or {}
                # Build Schema from JSON Schema parameters dict
                schema = _dict_to_schema(params, protos)
                fd = protos.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description or "",
                    parameters=schema,
                )
                declarations.append(fd)
            return declarations
        except ImportError:
            # Fallback for test environments without SDK
            return [
                type(
                    "FunctionDeclaration",
                    (),
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.parameters or {},
                    },
                )()
                for tool in tools
            ]

    def _convert_to_chat_response(self, response: Any) -> ChatResponse:
        """Convert a Gemini generate_content response to ChatResponse.

        * text parts        → TextBlock
        * thought parts     → ThinkingBlock
        * function_call     → ToolCallBlock + ToolCall with synthetic ``gemini_call_{uuid}`` ID

        Synthetic tool call IDs are generated because Gemini API does not return them.
        """
        content_blocks: list[Any] = []
        tool_calls: list[ToolCall] = []

        candidate = response.candidates[0] if response.candidates else None
        finish_reason: str | None = None

        if candidate is not None:
            finish_reason = str(getattr(candidate, "finish_reason", "STOP"))
            candidate_content = getattr(candidate, "content", None)
            if candidate_content is not None:
                for part in getattr(candidate_content, "parts", []):
                    # Check for thought (thinking) part
                    if getattr(part, "thought", False):
                        thinking_text = getattr(part, "text", "") or ""
                        content_blocks.append(
                            ThinkingBlock(thinking=thinking_text, signature="")
                        )
                        continue

                    # Check for text part
                    text = getattr(part, "text", None)
                    if text:
                        content_blocks.append(TextBlock(text=text))
                        continue

                    # Check for function_call part
                    function_call = getattr(part, "function_call", None)
                    if function_call is not None:
                        tool_name: str = getattr(function_call, "name", "") or ""
                        # Gemini args may be a Struct/MapComposite — convert to dict
                        raw_args: Any = getattr(function_call, "args", {})
                        tool_input: dict[str, Any] = _struct_to_dict(raw_args)

                        # Generate synthetic tool call ID
                        tool_id = f"gemini_call_{uuid.uuid4().hex}"

                        content_blocks.append(
                            ToolCallBlock(id=tool_id, name=tool_name, input=tool_input)
                        )
                        tool_calls.append(
                            ToolCall(id=tool_id, name=tool_name, arguments=tool_input)
                        )

        # --- Usage extraction ---
        usage_meta = getattr(response, "usage_metadata", None)
        input_tokens: int = getattr(usage_meta, "prompt_token_count", 0) or 0
        output_tokens: int = getattr(usage_meta, "candidates_token_count", 0) or 0

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
            finish_reason=finish_reason,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Call the Gemini generate_content_async API and return a ChatResponse.

        Builds params, handles thinking_budget if set, calls
        model.generate_content_async(), and converts response.
        """
        messages_list: list[Any] = list(request.messages)

        # Convert messages to Gemini format (returns contents + system_instruction)
        contents, system_instruction = self._convert_messages(messages_list)

        # Build generation config
        max_tokens_val: int = int(
            request.max_output_tokens or kwargs.get("max_tokens") or self.max_tokens
        )
        generation_config: dict[str, Any] = {
            "max_output_tokens": max_tokens_val,
        }

        temperature: float | None = (
            request.temperature if request.temperature is not None else None
        )
        if temperature is not None:
            generation_config["temperature"] = temperature

        # thinking_budget handling
        thinking_budget: int | None = (
            getattr(request, "thinking_budget", None)
            or kwargs.get("thinking_budget")
            or self.thinking_budget
        )
        if thinking_budget is not None:
            generation_config["thinking_config"] = {"thinking_budget": thinking_budget}

        # Build API call parameters
        api_params: dict[str, Any] = {
            "contents": contents,
            "generation_config": generation_config,
        }

        # System instruction
        if system_instruction:
            api_params["system_instruction"] = system_instruction

        # Tools
        if request.tools:
            gemini_tools = self._convert_tools_from_request(request.tools)
            if gemini_tools:
                try:
                    from google.generativeai import protos  # type: ignore[import-untyped]  # noqa: PLC0415

                    api_params["tools"] = [
                        protos.Tool(function_declarations=gemini_tools)
                    ]
                except ImportError:
                    api_params["tools"] = gemini_tools

        # Get model (lazy init)
        model = self._get_model()

        # API call
        try:
            response = await model.generate_content_async(**api_params)
        except Exception as exc:
            raise ProviderError(
                str(exc),
                retryable=True,
            ) from exc

        return self._convert_to_chat_response(response)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _struct_to_dict(value: Any) -> dict[str, Any]:
    """Convert a Gemini Struct/MapComposite to a plain Python dict."""
    if isinstance(value, dict):
        return value
    # Handle google.protobuf.struct_pb2.Struct or MapComposite
    if hasattr(value, "items"):
        return {k: _value_to_python(v) for k, v in value.items()}
    # Try JSON round-trip for proto objects
    try:
        import json  # noqa: PLC0415
        from google.protobuf import json_format  # type: ignore[import-untyped]  # noqa: PLC0415

        return json.loads(json_format.MessageToJson(value))
    except Exception:
        pass
    return {}


def _value_to_python(value: Any) -> Any:
    """Recursively convert a proto Value to a Python native type."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, dict):
        return {k: _value_to_python(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_value_to_python(v) for v in value]
    # MapComposite
    if hasattr(value, "items"):
        return {k: _value_to_python(v) for k, v in value.items()}
    return value


def _dict_to_schema(params: dict[str, Any], protos: Any) -> Any:
    """Convert a JSON Schema dict to a Gemini Schema proto object."""
    if not params:
        return None

    type_map = {
        "string": protos.Type.STRING,
        "number": protos.Type.NUMBER,
        "integer": protos.Type.INTEGER,
        "boolean": protos.Type.BOOLEAN,
        "array": protos.Type.ARRAY,
        "object": protos.Type.OBJECT,
    }

    type_str = params.get("type", "object")
    schema_type = type_map.get(type_str, protos.Type.OBJECT)

    properties: dict[str, Any] = {}
    raw_props = params.get("properties", {})
    for prop_name, prop_schema in raw_props.items():
        if isinstance(prop_schema, dict):
            properties[prop_name] = _dict_to_schema(prop_schema, protos)

    required: list[str] = params.get("required", [])
    description: str = params.get("description", "")

    return protos.Schema(
        type=schema_type,
        description=description,
        properties=properties if properties else None,
        required=required if required else None,
    )
