"""StreamingOrchestrator — IPC-native agent loop.

Every interaction with context, provider, hooks, and tools is performed via
JSON-RPC requests through ``client``.  No direct object references.

Core events (session, prompt, tool) are defined locally; content-block and
provider:response events are imported from amplifier_ipc_protocol.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from amplifier_ipc.protocol import (
    ChatRequest,
    ChatResponse,
    HookAction,
    HookResult,
    Message,
    ThinkingBlock,
    ToolCall,
    ToolResult,
    ToolSpec,  # noqa: F401 — required by spec; unused pending future tool spec handling
    orchestrator,
)
from amplifier_ipc_protocol.events import (
    CONTENT_BLOCK_DELTA,
    CONTENT_BLOCK_END,
    CONTENT_BLOCK_START,
    EXECUTION_END,
    EXECUTION_START,
    LLM_REQUEST,
    LLM_RESPONSE,
    PROVIDER_RESOLVE,
    PROVIDER_RESPONSE,
    PROVIDER_THROTTLE,  # noqa: F401 — Phase 2 event; wired in subsequent tasks
    THINKING_DELTA,  # noqa: F401 — Phase 2 event; wired in subsequent tasks
    THINKING_FINAL,  # noqa: F401 — Phase 2 event; wired in subsequent tasks
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event name constants — local definitions (remaining Phase-1 events; see import above for content_block/provider:response)
# ---------------------------------------------------------------------------

PROMPT_SUBMIT = "prompt:submit"
PROMPT_COMPLETE = "prompt:complete"
PROVIDER_REQUEST = "provider:request"
PROVIDER_ERROR = "provider:error"
PROVIDER_RETRY = "provider:retry"
TOOL_PRE = "tool:pre"
TOOL_POST = "tool:post"
TOOL_ERROR = "tool:error"
ORCHESTRATOR_COMPLETE = "orchestrator:complete"
ORCHESTRATOR_RATE_LIMIT_DELAY = "orchestrator:rate_limit_delay"
# CONTENT_BLOCK_START and CONTENT_BLOCK_END imported from amplifier_ipc_protocol.events
STREAM_THINKING = "stream.thinking"
STREAM_TOOL_CALL_START = "stream.tool_call_start"
STREAM_TOOL_CALL = "stream.tool_call"
STREAM_TOOL_RESULT = "stream.tool_result"
STREAM_TODO_UPDATE = "stream.todo_update"

# ---------------------------------------------------------------------------
# Provider retry configuration
# ---------------------------------------------------------------------------

_MAX_PROVIDER_RETRIES: int = 3
_PROVIDER_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)  # seconds per attempt


# ---------------------------------------------------------------------------
# StreamingOrchestrator
# ---------------------------------------------------------------------------


@orchestrator
class StreamingOrchestrator:
    """IPC-native streaming orchestrator.

    All context, provider, hook, and tool operations are routed through
    ``client.request()`` / ``client.send_notification()`` as JSON-RPC calls.
    """

    name = "streaming"

    def __init__(self) -> None:
        self.max_iterations: int = -1
        self.stream_delay: float = 0.01
        # NOTE: Not re-entrant — concurrent calls to execute() on the same instance
        # will corrupt _pending_ephemeral_injections. One instance per session.
        self._pending_ephemeral_injections: list[dict[str, Any]] = []
        self._last_provider_call_end: float | None = None
        self._cancelled: bool = False

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Signal the running execute() loop to stop at the next checkpoint.

        Safe to call from any coroutine.  The loop checks ``_cancelled`` at
        the top of each iteration and before dispatching tool calls, so
        cancellation is honoured promptly without aborting mid-tool-execution.
        """
        self._cancelled = True

    # ------------------------------------------------------------------
    # Public execute entry-point
    # ------------------------------------------------------------------

    async def execute(self, prompt: str, config: dict[str, Any], client: Any) -> str:
        """Run the agent loop and return the final response text.

        Args:
            prompt: The user's input prompt.
            config: Runtime configuration dict (may override defaults).
            client: IPC client — all calls go through here.

        Returns:
            The final assistant response text.
        """
        # --- emit execution:start (first event in execute) ---
        await self._hook_emit(client, EXECUTION_START, {"prompt": prompt})

        # Allow config overrides
        max_iterations: int = config.get("max_iterations", self.max_iterations)
        min_delay_ms: int = config.get("min_delay_between_calls_ms", 0)
        provider_name: str = config.get("provider_name", "unknown")

        _execution_status = "completed"
        _execution_response = ""

        try:
            # Reset per-execute state
            self._pending_ephemeral_injections = []
            self._last_provider_call_end = None
            self._cancelled = False

            # --- emit provider:resolve ---
            await self._hook_emit(client, PROVIDER_RESOLVE, {"provider": provider_name})

            # ----------------------------------------------------------------
            # Step 1: emit prompt:submit — check for DENY
            # ----------------------------------------------------------------
            submit_result = await self._hook_emit(
                client, PROMPT_SUBMIT, {"prompt": prompt}
            )

            if submit_result.action == HookAction.DENY:
                return f"Operation denied: {submit_result.reason}"

            # Store ephemeral injection from prompt:submit
            self._store_ephemeral_injection(submit_result)

            # ----------------------------------------------------------------
            # Step 2: add user message to context
            # ----------------------------------------------------------------
            user_msg = Message(role="user", content=prompt)
            await client.request(
                "request.context_add_message",
                {"message": user_msg.model_dump()},
            )

            # ----------------------------------------------------------------
            # Step 3: main agent loop
            # ----------------------------------------------------------------
            iteration = 0
            response_text = ""
            _was_cancelled = False

            while max_iterations == -1 or iteration < max_iterations:
                iteration += 1

                # --- cancellation checkpoint (top of iteration) ---
                if self._cancelled:
                    _was_cancelled = True
                    break

                # --- emit provider:request, check DENY ---
                req_result = await self._hook_emit(
                    client, PROVIDER_REQUEST, {"iteration": iteration}
                )
                if req_result.action == HookAction.DENY:
                    return f"Operation denied: {req_result.reason}"

                # --- get messages from context ---
                messages_raw = await client.request("request.context_get_messages", {})
                messages: list[Message] = [
                    Message.model_validate(m) for m in (messages_raw or [])
                ]

                # --- apply ephemeral injections from previous tool:post or prompt:submit ---
                messages = self._apply_ephemeral_injections(messages)

                # --- apply any context injection from provider:request hook ---
                if (
                    req_result.action == HookAction.INJECT_CONTEXT
                    and req_result.ephemeral
                    and req_result.context_injection
                ):
                    messages = self._inject_into_messages(
                        messages,
                        req_result.context_injection,
                        req_result.context_injection_role,
                        req_result.append_to_last_tool_result,
                    )

                # --- apply rate limit delay ---
                await self._apply_rate_limit_delay(client, min_delay_ms, iteration)

                # --- build ChatRequest ---
                chat_request = ChatRequest(
                    messages=messages,
                    tools=config.get("tools"),
                    reasoning_effort=config.get("reasoning_effort"),
                )

                # --- emit llm:request before provider call ---
                await self._hook_emit(
                    client,
                    LLM_REQUEST,
                    {
                        "provider": provider_name,
                        "message_count": len(messages),
                        "iteration": iteration,
                    },
                )

                # --- call provider.complete (with retry + exponential backoff) ---
                response_raw: Any = None
                for _attempt in range(_MAX_PROVIDER_RETRIES + 1):
                    try:
                        response_raw = await client.request(
                            "request.provider_complete",
                            {"request": chat_request.model_dump()},
                        )
                        break  # success — exit retry loop
                    except Exception as exc:
                        # Determine whether the error is retryable.
                        # Check both a top-level attribute and a nested data dict
                        # (e.g. JsonRpcError carries error details in .data).
                        retryable: bool = bool(getattr(exc, "retryable", False))
                        if not retryable:
                            exc_data = getattr(exc, "data", None)
                            if isinstance(exc_data, dict):
                                retryable = bool(exc_data.get("retryable", False))

                        is_last_attempt = _attempt >= _MAX_PROVIDER_RETRIES

                        if not retryable or is_last_attempt:
                            logger.error(
                                "Provider call failed on iteration %d (attempt %d/%d): %s",
                                iteration,
                                _attempt + 1,
                                _MAX_PROVIDER_RETRIES + 1,
                                exc,
                            )
                            await self._hook_emit(
                                client,
                                PROVIDER_ERROR,
                                {
                                    "iteration": iteration,
                                    "error": {
                                        "type": type(exc).__name__,
                                        "msg": str(exc),
                                    },
                                },
                            )
                            raise

                        # Retryable error — back off then retry.
                        delay = _PROVIDER_RETRY_DELAYS[_attempt]
                        logger.warning(
                            "Provider call failed (attempt %d/%d, retrying in %.1fs): %s",
                            _attempt + 1,
                            _MAX_PROVIDER_RETRIES + 1,
                            delay,
                            exc,
                        )
                        await self._hook_emit(
                            client,
                            PROVIDER_RETRY,
                            {
                                "attempt": _attempt + 1,
                                "max_retries": _MAX_PROVIDER_RETRIES,
                                "delay_s": delay,
                                "error": {
                                    "type": type(exc).__name__,
                                    "msg": str(exc),
                                },
                            },
                        )
                        await asyncio.sleep(delay)
                self._last_provider_call_end = time.monotonic()

                chat_response = ChatResponse.model_validate(response_raw)

                # --- emit llm:response after successful provider call ---
                await self._hook_emit(
                    client,
                    LLM_RESPONSE,
                    {
                        "provider": provider_name,
                        "usage": chat_response.usage,
                        "status": "ok",
                    },
                )

                # --- emit provider:response hook ---
                await self._hook_emit(
                    client,
                    PROVIDER_RESPONSE,
                    {
                        "provider": provider_name,
                        "response": response_raw,
                        "usage": chat_response.usage,
                    },
                )

                # --- extract response text ---
                response_text = self._extract_text(chat_response)

                # --- stream thinking notifications (before stream.token) ---
                if chat_response.content_blocks:
                    for _block_idx, block in enumerate(chat_response.content_blocks):
                        # Determine block type
                        if isinstance(block, dict):
                            _block_type = block.get("type", "unknown")
                        elif hasattr(block, "type"):
                            _block_type = block.type
                        else:
                            _block_type = "unknown"

                        # Emit content_block:start before processing
                        await self._hook_emit(
                            client,
                            CONTENT_BLOCK_START,
                            {"block_type": _block_type, "index": _block_idx},
                        )

                        # Extract block content for delta emission
                        if isinstance(block, ThinkingBlock):
                            thinking_text = block.thinking
                            _block_content = thinking_text or ""
                        elif (
                            isinstance(block, dict) and block.get("type") == "thinking"
                        ):
                            thinking_text = block.get("thinking", "")
                            _block_content = thinking_text
                        else:
                            thinking_text = None
                            # Text block: extract text content
                            if isinstance(block, dict):
                                _block_content = block.get("text", "")
                            elif hasattr(block, "text"):
                                _block_content = block.text or ""
                            else:
                                _block_content = ""

                        # Emit content_block:delta with the block's content
                        if _block_content:
                            await self._hook_emit(
                                client,
                                CONTENT_BLOCK_DELTA,
                                {
                                    "index": _block_idx,
                                    "block_type": _block_type,
                                    "delta": _block_content,
                                },
                            )

                        if thinking_text:
                            await client.send_notification(
                                STREAM_THINKING, {"thinking": thinking_text}
                            )

                        # Emit content_block:end after processing
                        await self._hook_emit(
                            client,
                            CONTENT_BLOCK_END,
                            {"block_type": _block_type, "index": _block_idx},
                        )

                # --- stream token notification ---
                if response_text:
                    await client.send_notification(
                        "stream.token", {"text": response_text}
                    )

                # --- add assistant message to context ---
                # Always store extracted text in content (not chat_response.content which
                # may include ToolCallBlock objects that duplicate the tool_calls field).
                assistant_msg = Message(
                    role="assistant",
                    content=response_text,
                    tool_calls=chat_response.tool_calls,
                )
                await client.request(
                    "request.context_add_message",
                    {"message": assistant_msg.model_dump()},
                )

                # --- if no tool calls, we're done ---
                if not chat_response.tool_calls:
                    break

                # --- cancellation checkpoint (before tool dispatch) ---
                if self._cancelled:
                    _was_cancelled = True
                    break

                # --- parallel tool dispatch ---
                tool_tasks = [
                    self._execute_tool(tc, client) for tc in chat_response.tool_calls
                ]
                tool_results = await asyncio.gather(*tool_tasks)

                # --- add tool results to context sequentially ---
                # Iterate in tool_call order (asyncio.gather preserves order).
                # Two fixes applied here:
                #
                # Fix 29 (ephemeral ordering): post_results are stored NOW, in
                # tool_call order, rather than in non-deterministic completion
                # order inside _execute_tool.
                #
                # Fix 31 (is_error visibility): when success is False, mark the
                # message with metadata["is_error"] = True so providers that
                # support it (e.g. Anthropic) can treat it as a tool error block.
                for (
                    tool_call_id,
                    tool_name,
                    content,
                    success,
                    post_result,
                ) in tool_results:
                    # Fix 29: queue ephemeral injection in original tool_call order.
                    if post_result is not None:
                        self._store_ephemeral_injection(post_result)

                    # Fix 31: add is_error metadata for failed tool results.
                    metadata: dict[str, Any] | None = (
                        {"is_error": True} if not success else None
                    )
                    tool_msg = Message(
                        role="tool",
                        name=tool_name,
                        tool_call_id=tool_call_id,
                        content=content,
                        metadata=metadata,
                    )
                    await client.request(
                        "request.context_add_message",
                        {"message": tool_msg.model_dump()},
                    )

            # ----------------------------------------------------------------
            # Cancellation: skip orchestrator:complete / prompt:complete and
            # return immediately.  The caller sees the last partial response.
            # ----------------------------------------------------------------
            if _was_cancelled:
                logger.info("Orchestrator cancelled after %d iteration(s)", iteration)
                _execution_status = "cancelled"
                _execution_response = response_text
                return response_text

            # warn if we hit max iterations
            max_iterations_hit = max_iterations != -1 and iteration >= max_iterations
            if max_iterations_hit:
                logger.warning("Max iterations (%d) reached", max_iterations)

            # ----------------------------------------------------------------
            # Step 4: emit orchestrator:complete
            # ----------------------------------------------------------------
            await self._hook_emit(
                client,
                ORCHESTRATOR_COMPLETE,
                {
                    "orchestrator": "streaming",
                    "turn_count": iteration,
                    "status": "max_iterations_reached"
                    if max_iterations_hit
                    else "success",
                },
            )

            # ----------------------------------------------------------------
            # Step 5: emit prompt:complete and return
            # ----------------------------------------------------------------
            await self._hook_emit(
                client,
                PROMPT_COMPLETE,
                {
                    "response_preview": response_text[:200],
                    "length": len(response_text),
                },
            )

            _execution_response = response_text
            return response_text
        except Exception:
            _execution_status = "error"
            raise
        finally:
            await self._hook_emit(
                client,
                EXECUTION_END,
                {"response": _execution_response, "status": _execution_status},
            )

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def _execute_tool(
        self, tool_call: ToolCall, client: Any
    ) -> tuple[str, str, str, bool, HookResult | None]:
        """Execute a single tool via IPC, returning (id, name, content, success, post_result).

        Never raises — errors become error-message strings.

        Returns:
            A 5-tuple of:
              - tool_call_id (str)
              - tool_name (str)
              - content (str): serialised tool output or error message
              - success (bool): False when the tool failed, was denied, or raised
              - post_result (HookResult | None): the tool:post hook result, used to
                queue ephemeral injections in tool_call order after gather() completes;
                None when no post hook was run (deny/ask_user/exception paths).
        """
        try:
            # --- emit stream.tool_call_start (before tool:pre hook) ---
            await client.send_notification(
                STREAM_TOOL_CALL_START, {"tool_name": tool_call.name}
            )

            # --- emit stream.tool_call with name and arguments ---
            await client.send_notification(
                STREAM_TOOL_CALL,
                {"tool_name": tool_call.name, "arguments": tool_call.arguments},
            )

            # --- emit tool:pre, check DENY ---
            pre_result = await self._hook_emit(
                client,
                TOOL_PRE,
                {
                    "tool_name": tool_call.name,
                    "tool_call_id": tool_call.id,
                    "tool_input": tool_call.arguments,
                },
            )
            if pre_result.action == HookAction.DENY:
                return (
                    tool_call.id,
                    tool_call.name,
                    f"Denied by hook: {pre_result.reason}",
                    False,
                    None,
                )

            # --- call tool.execute ---
            tool_result_raw = await client.request(
                "request.tool_execute",
                {"name": tool_call.name, "input": tool_call.arguments},
            )
            tool_result = ToolResult.model_validate(tool_result_raw or {})

            # --- emit tool:post ---
            result_data = tool_result.model_dump()
            post_result = await self._hook_emit(
                client,
                TOOL_POST,
                {
                    "tool_name": tool_call.name,
                    "tool_call_id": tool_call.id,
                    "tool_input": tool_call.arguments,
                    "result": result_data,
                },
            )

            # NOTE: ephemeral injection is NOT stored here.  All tool:post
            # post_results are returned and processed in tool_call order by
            # the caller after asyncio.gather() completes (Task 29 fix).

            # Check if hook MODIFY-ed the tool result
            content = tool_result.get_serialized_output()
            if post_result.data is not None:
                returned = post_result.data.get("result")
                if returned is not None:
                    if isinstance(returned, (dict, list)):
                        content = json.dumps(returned)
                    else:
                        content = str(returned)

            # --- emit stream.tool_result ---
            await client.send_notification(
                STREAM_TOOL_RESULT,
                {
                    "tool_name": tool_call.name,
                    "success": getattr(tool_result, "success", True),
                    "output": content[:2000],
                },
            )

            # --- emit stream.todo_update for todo tool calls ---
            if tool_call.name == "todo":
                try:
                    parsed = (
                        json.loads(content) if isinstance(content, str) else content
                    )
                    if isinstance(parsed, dict) and "todos" in parsed:
                        await client.send_notification(
                            STREAM_TODO_UPDATE,
                            {
                                "todos": parsed["todos"],
                                "status": parsed.get("status", "updated"),
                            },
                        )
                except (json.JSONDecodeError, TypeError):
                    logger.debug(
                        "stream.todo_update skipped: could not parse todo tool output"
                    )

            return (
                tool_call.id,
                tool_call.name,
                content,
                tool_result.success,
                post_result,
            )

        except Exception as exc:
            logger.error("Tool %s failed: %s", tool_call.name, exc)
            await self._hook_emit(
                client,
                TOOL_ERROR,
                {
                    "tool_name": tool_call.name,
                    "tool_call_id": tool_call.id,
                    "error": {"type": type(exc).__name__, "msg": str(exc)},
                },
            )
            # --- emit stream.tool_result for error path ---
            await client.send_notification(
                STREAM_TOOL_RESULT,
                {
                    "tool_name": tool_call.name,
                    "success": False,
                    "output": f"Error: {exc}"[:2000],
                },
            )
            return (
                tool_call.id,
                tool_call.name,
                f"Internal error executing tool: {exc}",
                False,
                None,
            )

    # ------------------------------------------------------------------
    # Rate limit
    # ------------------------------------------------------------------

    async def _apply_rate_limit_delay(
        self, client: Any, min_delay_ms: int, iteration: int
    ) -> None:
        """Delay if configured and the inter-call gap is too short."""
        if min_delay_ms <= 0 or self._last_provider_call_end is None:
            return

        elapsed_ms = (time.monotonic() - self._last_provider_call_end) * 1000
        remaining_ms = min_delay_ms - elapsed_ms

        if remaining_ms > 0:
            await self._hook_emit(
                client,
                ORCHESTRATOR_RATE_LIMIT_DELAY,
                {
                    "delay_ms": remaining_ms,
                    "configured_ms": min_delay_ms,
                    "elapsed_ms": elapsed_ms,
                    "iteration": iteration,
                },
            )
            await asyncio.sleep(remaining_ms / 1000)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _hook_emit(
        self, client: Any, event: str, data: dict[str, Any]
    ) -> HookResult:
        """Emit a hook event via IPC and parse the returned HookResult."""
        raw = await client.request("request.hook_emit", {"event": event, "data": data})
        if raw is None:
            return HookResult()
        if isinstance(raw, HookResult):
            return raw
        return HookResult.model_validate(raw)

    def _store_ephemeral_injection(self, result: HookResult) -> None:
        """If the hook result requests ephemeral injection, queue it."""
        if (
            result.action == HookAction.INJECT_CONTEXT
            and result.ephemeral
            and result.context_injection
        ):
            self._pending_ephemeral_injections.append(
                {
                    "role": result.context_injection_role,
                    "content": result.context_injection,
                    "append_to_last_tool_result": result.append_to_last_tool_result,
                }
            )
            logger.debug("Queued ephemeral injection from hook result")

    def _apply_ephemeral_injections(self, messages: list[Message]) -> list[Message]:
        """Apply (and clear) any pending ephemeral injections to the message list."""
        if not self._pending_ephemeral_injections:
            return messages

        result = list(messages)
        for injection in self._pending_ephemeral_injections:
            result = self._inject_into_messages(
                result,
                injection["content"],
                injection["role"],
                injection.get("append_to_last_tool_result", False),
            )
        self._pending_ephemeral_injections = []
        return result

    @staticmethod
    def _inject_into_messages(
        messages: list[Message],
        content: str,
        role: str,
        append_to_last_tool_result: bool,
    ) -> list[Message]:
        """Append an ephemeral injection to the message list."""
        result = list(messages)
        if append_to_last_tool_result and result and result[-1].role == "tool":
            last = result[-1]
            original = last.content or ""
            result[-1] = last.model_copy(update={"content": f"{original}\n\n{content}"})
        else:
            result.append(Message(role=role, content=content))
        return result

    @staticmethod
    def _extract_text(response: ChatResponse) -> str:
        """Extract a plain text string from a ChatResponse."""
        if response.text:
            return response.text
        if isinstance(response.content, str):
            return response.content
        if isinstance(response.content, list):
            parts = []
            for block in response.content:
                if isinstance(block, dict):
                    text = block.get("text", "")
                elif hasattr(block, "text"):
                    text = block.text
                else:
                    text = ""
                if text:
                    parts.append(text)
            return "\n\n".join(parts)
        return ""
