"""SimpleContextManager — in-memory context manager with ephemeral compaction."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from amplifier_ipc.protocol import Message, ToolCall, context_manager
from amplifier_ipc_protocol.events import (
    CONTEXT_COMPACTION,
    CONTEXT_POST_COMPACT,
    CONTEXT_PRE_COMPACT,
)


logger = logging.getLogger(__name__)


@context_manager
class SimpleContextManager:
    """
    In-memory context manager with EPHEMERAL compaction.

    Key Principle: self.messages is the source of truth and is NEVER modified
    by compaction. Compaction only returns a compacted VIEW for the current
    LLM request.

    Owns memory policy: orchestrators ask for messages via get_messages(),
    and this context manager decides how to fit them within limits. Compaction is
    handled internally and ephemerally - the original history is always preserved.

    Compaction Strategy (Progressive Interleaved):
    Triggered when usage >= compact_threshold (default 85%), target is target_usage (default 60%).

    Each level checks after every operation and stops as soon as target is reached:

    Level 1: Truncate oldest 25% of tool results
    Level 2: Truncate next 25% of tool results (now 50% truncated)
    Level 3: Remove oldest messages (use configured protected_recent)
    Level 4: Truncate next 25% of tool results (now 75% truncated)
    Level 5: Remove more messages (60% of configured protection)
    Level 6: Truncate remaining tool results (except last N)
    Level 7: Remove more messages (30% of configured protection - last resort)
    Level 8: Stub first user message + remove old stubs (extreme pressure)

    This interleaved approach ensures minimal data loss by:
    - Preferring truncation (preserves structure) over removal (loses context)
    - Progressively relaxing protection as pressure increases
    - Respecting configured protected_recent as baseline, only relaxing under pressure
    - Always protecting: system messages, last user message, last N tool results, tool pairs
    - First user message: stubbable at Level 8, but never fully removed
    """

    name = "simple"

    def __init__(self) -> None:
        """Initialize the context manager with sensible defaults."""
        self.messages: list[Message] = []
        # Injected by the protocol server before get_messages() is called.
        # Enables hook event emission (e.g. compaction events).
        self.client: Any = None
        self.max_tokens: int = 200_000
        self.compact_threshold: float = 0.85
        self.target_usage: float = 0.60
        self.protected_recent: float = 0.30
        self.protected_tool_results: int = 5
        self.truncate_chars: int = 8000
        self.compaction_notice_enabled: bool = True
        self.compaction_notice_token_reserve: int = 2000
        self.compaction_notice_verbosity: str = "normal"
        self.compaction_notice_min_level: int = 3
        self.output_reserve_fraction: float = 0.25
        self._last_compaction_stats: dict[str, Any] | None = None

    async def _emit_hook(self, event: str, data: dict[str, Any]) -> None:
        """Emit a hook event via the injected IPC client.

        No-ops when client is None. Swallows exceptions to avoid disrupting
        the main context manager flow.
        """
        if self.client is None:
            return
        try:
            await self.client.request(
                "request.hook_emit", {"event": event, "data": data}
            )
        except Exception:
            logger.debug("Failed to emit hook event %r", event)

    async def add_message(self, message: Message) -> None:
        """Add a message to the context.

        Messages are always accepted. Compaction happens ephemerally when
        get_messages() is called before LLM requests.

        Tool results MUST be added even if over threshold, otherwise
        tool_use/tool_result pairing breaks.

        Timestamps are automatically added to message metadata for replay timing.
        Existing timestamps and metadata are preserved.
        """
        # Add timestamp in metadata if not already present (for replay timing)
        existing_meta = getattr(message, "metadata", None) or {}
        if "timestamp" not in existing_meta:
            message = message.model_copy(
                update={
                    "metadata": {
                        **existing_meta,
                        "timestamp": datetime.now(UTC).isoformat(
                            timespec="milliseconds"
                        ),
                    },
                }
            )

        # Add message (no rejection - compaction happens ephemerally)
        self.messages.append(message)

        token_count = self._estimate_tokens(self.messages)
        usage = token_count / self.max_tokens
        logger.debug(
            f"Added message: {message.role} - "
            f"{len(self.messages)} total messages, {token_count:,} tokens "
            f"({usage:.1%})"
        )

    async def get_messages(self, provider_info: dict[str, Any]) -> list[Message]:
        """
        Get messages ready for an LLM request.

        Applies EPHEMERAL compaction if needed - returns a NEW list without
        modifying self.messages. The original history is always preserved.

        If compaction occurs and notice is enabled, a system-reminder is inserted
        at position 1 (after main system message) to inform the LLM about what
        was compacted.

        Args:
            provider_info: Dict with optional provider context info such as
                'context_window' and 'max_output_tokens' for budget calculation.

        Returns:
            Messages ready for LLM request, compacted if necessary.
        """
        budget = self._calculate_budget(provider_info)

        # Reserve token budget for potential compaction notice (if enabled)
        effective_budget = budget
        if self.compaction_notice_enabled:
            effective_budget = budget - self.compaction_notice_token_reserve
            logger.debug(
                f"Reserved {self.compaction_notice_token_reserve} tokens for potential notice "
                f"(effective budget: {effective_budget:,})"
            )

        # Use messages as-is (static mode - no system prompt factory)
        working_messages = list(self.messages)

        token_count = self._estimate_tokens(working_messages)

        # Check if compaction needed (using effective budget with notice reserve deducted)
        if self._should_compact(token_count, effective_budget):
            # Emit pre-compaction event
            await self._emit_hook(
                CONTEXT_PRE_COMPACT,
                {"message_count": len(working_messages), "token_count": token_count},
            )

            # Compact EPHEMERALLY - returns new list, working_messages unchanged
            compacted = await self._compact_ephemeral(
                effective_budget, working_messages
            )
            logger.info(
                f"Ephemeral compaction: {len(working_messages)} -> {len(compacted)} messages for this request"
            )

            # Emit post-compaction events
            compacted_token_count = self._estimate_tokens(compacted)
            await self._emit_hook(
                CONTEXT_POST_COMPACT,
                {"message_count": len(compacted), "token_count": compacted_token_count},
            )
            if self._last_compaction_stats:
                await self._emit_hook(CONTEXT_COMPACTION, self._last_compaction_stats)

            # Insert compaction notice if enabled and level threshold met
            if self.compaction_notice_enabled and self._last_compaction_stats:
                level = self._last_compaction_stats.get("strategy_level", 0)
                if level >= self.compaction_notice_min_level:
                    notice = self._format_compaction_notice()
                    if notice:
                        # Insert at position 1 (after main system message at position 0)
                        compacted.insert(
                            1,
                            Message(
                                role="system",
                                content=notice,
                                metadata={
                                    "source": "context-compaction",
                                    "ephemeral": True,
                                },
                            ),
                        )
                        logger.debug(
                            f"Inserted compaction notice at position 1 (level {level}, "
                            f"verbosity: {self.compaction_notice_verbosity})"
                        )

            return compacted

        return working_messages

    async def set_messages(self, messages: list[Message]) -> None:
        """Set messages from a saved transcript (for session resume)."""
        self.messages = list(messages)
        logger.info(f"Restored {len(messages)} messages to context")

    async def clear(self) -> None:
        """Clear all messages."""
        self.messages = []
        logger.info("Context cleared")

    async def should_compact(self) -> bool:
        """Check if context should be compacted.

        Note: This module uses ephemeral compaction during get_messages(),
        so this always returns False. The actual compaction check happens internally.
        This method exists to satisfy the ContextManager protocol.
        """
        return False

    async def compact(self) -> None:
        """Compact the context.

        Note: This module uses ephemeral compaction during get_messages(),
        so this is a no-op. Compaction happens automatically when getting messages.
        This method exists to satisfy the ContextManager protocol.
        """
        pass

    def _should_compact(self, token_count: int, budget: int) -> bool:
        """Check if context should be compacted."""
        usage = token_count / budget if budget > 0 else 0
        should = usage >= self.compact_threshold
        if should:
            logger.info(
                f"Context at {usage:.1%} capacity ({token_count:,}/{budget:,} tokens), "
                f"threshold {self.compact_threshold:.0%} - compaction needed"
            )
        return should

    async def _compact_ephemeral(
        self, budget: int, source_messages: list[Message] | None = None
    ) -> list[Message]:
        """
        Compact the context EPHEMERALLY using progressive interleaved strategy.

        This returns a NEW list - the source messages are NEVER modified.

        CRITICAL: System messages are NEVER compacted. They are extracted at the start
        and re-inserted at the end, guaranteeing they are always preserved regardless
        of compaction pressure.

        Progressive levels (each checks after every operation, stops when at target):
        - Level 1: Truncate oldest 25% of tool results
        - Level 2: Truncate next 25% (now 50% truncated)
        - Level 3: Remove oldest messages (protect 50%)
        - Level 4: Truncate next 25% (now 75% truncated)
        - Level 5: Remove more messages (protect 30%)
        - Level 6: Truncate remaining (except last N)
        - Level 7: Remove more messages (protect 10%)

        Anthropic API requires that tool_use blocks in message N have matching tool_result
        blocks in message N+1. These pairs are treated as atomic units during compaction.

        Args:
            budget: Token budget for compaction target calculation.
            source_messages: Messages to compact. If None, uses self.messages.
        """
        messages_to_compact = (
            source_messages if source_messages is not None else self.messages
        )
        target_tokens = int(budget * self.target_usage)
        old_count = len(messages_to_compact)
        old_tokens = self._estimate_tokens(messages_to_compact)

        logger.info(
            f"Compacting context: {len(messages_to_compact)} messages, {old_tokens:,} tokens "
            f"(target: {target_tokens:,} tokens, {self.target_usage:.0%} of {budget:,})"
        )

        # === CRITICAL: Extract system messages FIRST - they are NEVER compacted ===
        system_messages = [
            msg.model_copy() for msg in messages_to_compact if msg.role == "system"
        ]
        non_system_messages = [
            msg for msg in messages_to_compact if msg.role != "system"
        ]

        if system_messages:
            system_tokens = self._estimate_tokens(system_messages)
            logger.info(
                f"Preserving {len(system_messages)} system message(s) ({system_tokens:,} tokens) - "
                f"these are NEVER compacted"
            )

        # Work on non-system messages only - system messages bypass all compaction
        working_messages = [msg.model_copy() for msg in non_system_messages]
        current_tokens = old_tokens

        # Get all tool result indices for wave-based truncation
        tool_result_indices = [
            i for i, msg in enumerate(working_messages) if msg.role == "tool"
        ]
        total_tools = len(tool_result_indices)

        # Always protect the last N tool results from truncation
        protected_tool_indices = set(
            tool_result_indices[-self.protected_tool_results :]
        )

        # Calculate wave boundaries (25% chunks)
        wave1_end = int(total_tools * 0.25)
        wave2_end = int(total_tools * 0.50)

        total_truncated = 0
        total_removed = 0
        total_stubbed = 0
        max_level_reached = 1

        # === LEVEL 1: Truncate oldest 25% of tool results ===
        truncated, current_tokens = self._truncate_tool_wave(
            working_messages,
            tool_result_indices[:wave1_end],
            protected_tool_indices,
            target_tokens,
            current_tokens,
        )
        total_truncated += truncated
        if current_tokens <= target_tokens:
            logger.info(f"Level 1: Truncated {truncated} tool results, reached target")
            return await self._finalize_compaction_with_stats(
                working_messages,
                system_messages,
                old_count,
                old_tokens,
                total_removed,
                total_truncated,
                total_stubbed,
                max_level_reached,
                budget,
                target_tokens,
            )

        # === LEVEL 2: Truncate next 25% (now 50% truncated) ===
        max_level_reached = 2
        truncated, current_tokens = self._truncate_tool_wave(
            working_messages,
            tool_result_indices[wave1_end:wave2_end],
            protected_tool_indices,
            target_tokens,
            current_tokens,
        )
        total_truncated += truncated
        if current_tokens <= target_tokens:
            logger.info(
                f"Level 2: Truncated {truncated} more tool results, reached target"
            )
            return await self._finalize_compaction_with_stats(
                working_messages,
                system_messages,
                old_count,
                old_tokens,
                total_removed,
                total_truncated,
                total_stubbed,
                max_level_reached,
                budget,
                target_tokens,
            )

        # === LEVEL 3: Remove oldest messages (use configured protection) ===
        max_level_reached = 3
        level3_protection = self.protected_recent  # Use configured value
        working_messages, removed, stubbed, current_tokens = (
            self._remove_messages_with_protection(
                working_messages, target_tokens, protected_recent=level3_protection
            )
        )
        total_removed += removed
        total_stubbed += stubbed
        if current_tokens <= target_tokens:
            logger.info(
                f"Level 3: Removed {removed} messages, stubbed {stubbed} ({level3_protection:.0%} protected), reached target"
            )
            return await self._finalize_compaction_with_stats(
                working_messages,
                system_messages,
                old_count,
                old_tokens,
                total_removed,
                total_truncated,
                total_stubbed,
                max_level_reached,
                budget,
                target_tokens,
            )

        # === LEVEL 4: Truncate next 25% (now 75% truncated) ===
        max_level_reached = 4
        # Recalculate indices after removal
        tool_result_indices = [
            i for i, msg in enumerate(working_messages) if msg.role == "tool"
        ]
        protected_tool_indices = set(
            tool_result_indices[-self.protected_tool_results :]
        )
        wave3_start = int(len(tool_result_indices) * 0.50)
        wave3_end = int(len(tool_result_indices) * 0.75)

        truncated, current_tokens = self._truncate_tool_wave(
            working_messages,
            tool_result_indices[wave3_start:wave3_end],
            protected_tool_indices,
            target_tokens,
            current_tokens,
        )
        total_truncated += truncated
        if current_tokens <= target_tokens:
            logger.info(
                f"Level 4: Truncated {truncated} more tool results, reached target"
            )
            return await self._finalize_compaction_with_stats(
                working_messages,
                system_messages,
                old_count,
                old_tokens,
                total_removed,
                total_truncated,
                total_stubbed,
                max_level_reached,
                budget,
                target_tokens,
            )

        # === LEVEL 5: Remove more messages (60% of configured protection) ===
        max_level_reached = 5
        level5_protection = self.protected_recent * 0.6
        working_messages, removed, stubbed, current_tokens = (
            self._remove_messages_with_protection(
                working_messages, target_tokens, protected_recent=level5_protection
            )
        )
        total_removed += removed
        total_stubbed += stubbed
        if current_tokens <= target_tokens:
            logger.info(
                f"Level 5: Removed {removed} messages, stubbed {stubbed} ({level5_protection:.0%} protected), reached target"
            )
            return await self._finalize_compaction_with_stats(
                working_messages,
                system_messages,
                old_count,
                old_tokens,
                total_removed,
                total_truncated,
                total_stubbed,
                max_level_reached,
                budget,
                target_tokens,
            )

        # === LEVEL 6: Truncate remaining tool results (except last N) ===
        max_level_reached = 6
        tool_result_indices = [
            i for i, msg in enumerate(working_messages) if msg.role == "tool"
        ]
        protected_tool_indices = set(
            tool_result_indices[-self.protected_tool_results :]
        )

        truncated, current_tokens = self._truncate_tool_wave(
            working_messages,
            tool_result_indices,
            protected_tool_indices,
            target_tokens,
            current_tokens,
        )
        total_truncated += truncated
        if current_tokens <= target_tokens:
            logger.info(
                f"Level 6: Truncated {truncated} remaining tool results, reached target"
            )
            return await self._finalize_compaction_with_stats(
                working_messages,
                system_messages,
                old_count,
                old_tokens,
                total_removed,
                total_truncated,
                total_stubbed,
                max_level_reached,
                budget,
                target_tokens,
            )

        # === LEVEL 7: Remove more messages (30% of configured protection - last resort) ===
        max_level_reached = 7
        level7_protection = self.protected_recent * 0.3
        working_messages, removed, stubbed, current_tokens = (
            self._remove_messages_with_protection(
                working_messages, target_tokens, protected_recent=level7_protection
            )
        )
        total_removed += removed
        total_stubbed += stubbed

        logger.info(
            f"Level 7 complete ({level7_protection:.0%} protected): "
            f"Truncated {total_truncated} total, removed {total_removed} total, stubbed {total_stubbed} total. "
            f"Tokens: {old_tokens:,} → {current_tokens:,}"
        )

        # Check if we still need more space
        if current_tokens > target_tokens:
            # === LEVEL 8: Stub first user message + remove old stubs (extreme pressure) ===
            max_level_reached = 8

            # Find first user message and stub it if not already stubbed
            first_user_idx = None
            last_user_idx = None
            for i, msg in enumerate(working_messages):
                if msg.role == "user":
                    if first_user_idx is None:
                        first_user_idx = i
                    last_user_idx = i

            # Stub first user message (previously protected) - but NEVER if it's also the last
            if first_user_idx is not None and first_user_idx != last_user_idx:
                first_msg = working_messages[first_user_idx]
                if not getattr(first_msg, "_stubbed", None):
                    content = first_msg.content or ""
                    if isinstance(content, str) and len(content) > 80:
                        working_messages[first_user_idx] = self._stub_user_message(
                            first_msg
                        )
                        total_stubbed += 1
                        savings = (len(content) - 70) // 4
                        current_tokens -= savings
                        logger.info(
                            f"Level 8: Stubbed first user message (saved ~{savings} tokens)"
                        )

            # Remove old stubs if still over target (oldest first, outside protected zone)
            if current_tokens > target_tokens:
                protected_boundary = int(
                    len(working_messages) * (1 - level7_protection)
                )
                old_stub_indices = [
                    i
                    for i, msg in enumerate(working_messages)
                    if getattr(msg, "_stubbed", None)
                    and i < protected_boundary  # Outside protected recent zone
                    and i != last_user_idx  # Never remove last user message
                ]

                stubs_removed = 0
                indices_to_remove = set()
                for i in old_stub_indices:  # Already sorted oldest-first
                    if current_tokens <= target_tokens:
                        break
                    indices_to_remove.add(i)
                    stubs_removed += 1
                    current_tokens -= 18  # Stub is ~70 chars = ~18 tokens

                if indices_to_remove:
                    working_messages = [
                        msg
                        for i, msg in enumerate(working_messages)
                        if i not in indices_to_remove
                    ]
                    total_removed += stubs_removed
                    logger.info(f"Level 8: Removed {stubs_removed} old user stubs")

            logger.info(
                f"Level 8 complete (extreme pressure): "
                f"Stubbed {total_stubbed} total, removed {total_removed} total. "
                f"Tokens: {old_tokens:,} → {current_tokens:,}"
            )

        return await self._finalize_compaction_with_stats(
            working_messages,
            system_messages,
            old_count,
            old_tokens,
            total_removed,
            total_truncated,
            total_stubbed,
            max_level_reached,
            budget,
            target_tokens,
        )

    def _truncate_tool_wave(
        self,
        messages: list[Message],
        indices: list[int],
        protected_indices: set[int],
        target_tokens: int,
        current_tokens: int,
    ) -> tuple[int, int]:
        """
        Truncate a wave of tool results, stopping when target is reached.

        Returns (truncated_count, new_token_count).
        """
        truncated = 0
        for i in indices:
            if current_tokens <= target_tokens:
                break
            if i in protected_indices:
                continue
            if i >= len(messages):  # Index may be stale after removals
                continue
            msg = messages[i]
            if msg.role != "tool":  # Verify it's still a tool message
                continue
            if not getattr(msg, "_truncated", None):
                messages[i] = self._truncate_tool_result(msg)
                truncated += 1
                current_tokens = self._estimate_tokens(messages)
        return truncated, current_tokens

    def _remove_messages_with_protection(
        self,
        messages: list[Message],
        target_tokens: int,
        protected_recent: float,
    ) -> tuple[list[Message], int, int, int]:
        """
        Remove oldest messages with specified protection level.

        User messages are NEVER removed - they may be stubbed if still over target.

        Returns (new_messages, removed_count, stubbed_count, new_token_count).
        """
        # Determine protected indices
        protected_indices = set()

        # Track user messages for stubbing (NEVER removal)
        user_message_indices = {
            i for i, msg in enumerate(messages) if msg.role == "user"
        }

        # Find first and last user message indices
        first_user_idx = None
        last_user_idx = None
        for i, msg in enumerate(messages):
            if msg.role == "user":
                if first_user_idx is None:
                    first_user_idx = i
                last_user_idx = i

        # Always protect system messages
        for i, msg in enumerate(messages):
            if msg.role == "system":
                protected_indices.add(i)

        # Always protect the LAST user message (current context)
        if last_user_idx is not None:
            protected_indices.add(last_user_idx)

        # Protect last N% of messages (using the passed protection level)
        protected_boundary = int(len(messages) * (1 - protected_recent))
        for i in range(protected_boundary, len(messages)):
            protected_indices.add(i)

        # Removal candidates exclude ALL user messages (they can only be stubbed, not removed)
        removal_candidates = [
            i
            for i in range(len(messages))
            if i not in protected_indices and i not in user_message_indices
        ]

        # Remove messages until under target, preserving tool pairs
        indices_to_remove = set()
        current_tokens = self._estimate_tokens(messages)

        for i in removal_candidates:
            if current_tokens <= target_tokens:
                break

            msg = messages[i]

            # Handle tool result - must remove with its tool_use pair
            if msg.role == "tool":
                pair_removed = self._try_remove_tool_pair_from_result(
                    messages, i, protected_indices, indices_to_remove
                )
                if not pair_removed:
                    continue  # Can't remove this one, skip

            # Handle assistant with tool_calls - must remove with all its tool results
            elif msg.role == "assistant" and msg.tool_calls:
                pair_removed = self._try_remove_tool_pair_from_assistant(
                    messages, i, msg, protected_indices, indices_to_remove
                )
                if not pair_removed:
                    continue  # Can't remove this one, skip

            # Regular message - just mark for removal
            else:
                indices_to_remove.add(i)

            # Update token estimate after each removal decision
            removed_tokens = sum(
                len(str(messages[idx])) // 4 for idx in indices_to_remove
            )
            current_tokens = self._estimate_tokens(messages) - removed_tokens

        # After removals, stub intermediate user messages if still over target
        stub_candidates = sorted(
            [
                i
                for i in user_message_indices
                if i not in protected_indices
                and i != first_user_idx  # Protected from stubbing at levels 1-7
                and i != last_user_idx  # Always protected (never stubbed)
                and not getattr(messages[i], "_stubbed", None)  # Don't re-stub
            ]
        )

        indices_to_stub = set()
        for i in stub_candidates:
            if current_tokens <= target_tokens:
                break
            msg = messages[i]
            content = msg.content or ""
            if isinstance(content, str) and len(content) > 80:
                indices_to_stub.add(i)
                savings = (len(content) - 70) // 4  # Stub is ~70 chars
                current_tokens -= savings

        # Build result with stubs
        result = []
        for i, msg in enumerate(messages):
            if i in indices_to_remove:
                continue
            if i in indices_to_stub:
                result.append(self._stub_user_message(msg))
            else:
                result.append(msg)

        final_tokens = self._estimate_tokens(result)

        return result, len(indices_to_remove), len(indices_to_stub), final_tokens

    def _try_remove_tool_pair_from_result(
        self,
        messages: list[Message],
        result_idx: int,
        protected_indices: set[int],
        indices_to_remove: set[int],
    ) -> bool:
        """Try to remove a tool result and its paired assistant. Returns True if successful."""
        # Find the assistant with tool_calls
        for j in range(result_idx - 1, -1, -1):
            check_msg = messages[j]
            if check_msg.role == "assistant" and check_msg.tool_calls:
                if j in protected_indices:
                    return False  # Can't remove protected assistant

                # Check if ALL tool_results for this assistant can be removed
                all_removable, tool_result_indices = self._check_tool_pair_removable(
                    messages, check_msg, protected_indices
                )

                if all_removable:
                    indices_to_remove.add(j)
                    for k in tool_result_indices:
                        indices_to_remove.add(k)
                    return True
                return False
            if check_msg.role != "tool":
                break
        return False

    def _try_remove_tool_pair_from_assistant(
        self,
        messages: list[Message],
        assistant_idx: int,
        assistant_msg: Message,
        protected_indices: set[int],
        indices_to_remove: set[int],
    ) -> bool:
        """Try to remove an assistant with tool_calls and all its results. Returns True if successful."""
        all_removable, tool_result_indices = self._check_tool_pair_removable(
            messages, assistant_msg, protected_indices
        )

        if all_removable:
            indices_to_remove.add(assistant_idx)
            for k in tool_result_indices:
                indices_to_remove.add(k)
            return True
        return False

    def _check_tool_pair_removable(
        self,
        messages: list[Message],
        assistant_msg: Message,
        protected_indices: set[int],
    ) -> tuple[bool, list[int]]:
        """Check if all tool results for an assistant can be removed. Returns (all_removable, result_indices)."""
        all_removable = True
        tool_result_indices = []

        for tc in assistant_msg.tool_calls or []:
            tc_id = (
                tc.id
                if isinstance(tc, ToolCall)
                else (tc.get("id") or tc.get("tool_call_id"))
            )
            if tc_id:
                for k, m in enumerate(messages):
                    if m.tool_call_id == tc_id:
                        if k in protected_indices:
                            all_removable = False
                        else:
                            tool_result_indices.append(k)

        return all_removable, tool_result_indices

    async def _finalize_compaction_with_stats(
        self,
        working_messages: list[Message],
        system_messages: list[Message],
        old_count: int,
        old_tokens: int,
        total_removed: int,
        total_truncated: int,
        total_stubbed: int,
        max_level_reached: int,
        budget: int,
        target_tokens: int,
    ) -> list[Message]:
        """Log final compaction state, store stats, and return the result.

        CRITICAL: This function prepends the preserved system messages to the compacted
        working messages, ensuring system messages are ALWAYS in the final result.
        """
        # === CRITICAL: Prepend system messages to final result ===
        final_messages = system_messages + working_messages

        final_tokens = self._estimate_tokens(final_messages)
        system_count = len(system_messages)
        tool_use_count = sum(1 for m in final_messages if m.tool_calls)
        tool_result_count = sum(1 for m in final_messages if m.role == "tool")

        logger.info(
            f"Compaction complete: {old_count} → {len(final_messages)} messages, "
            f"{old_tokens:,} → {final_tokens:,} tokens "
            f"({system_count} system, {tool_use_count} tool_use, {tool_result_count} tool_result preserved)"
        )

        # === SANITY CHECK: Verify system messages are present ===
        result_system_count = sum(1 for m in final_messages if m.role == "system")
        if result_system_count != system_count:
            logger.error(
                f"CRITICAL: System message count mismatch! Expected {system_count}, got {result_system_count}. "
                f"This indicates a bug in compaction logic."
            )

        # Build and store stats for observability
        stats = {
            "before_tokens": old_tokens,
            "after_tokens": final_tokens,
            "before_messages": old_count,
            "after_messages": len(final_messages),
            "messages_removed": total_removed,
            "messages_truncated": total_truncated,
            "user_messages_stubbed": total_stubbed,
            "system_messages_preserved": system_count,
            "strategy_level": max_level_reached,
            "budget": budget,
            "target_tokens": target_tokens,
            "protected_recent": self.protected_recent,
            "protected_tool_results": self.protected_tool_results,
        }
        self._last_compaction_stats = stats

        return final_messages

    def _truncate_tool_result(self, msg: Message) -> Message:
        """
        Truncate a tool result message to reduce token count.

        Returns a NEW Message - does not modify the original.
        """
        content = msg.content or ""
        if not isinstance(content, str) or len(content) <= self.truncate_chars:
            return msg

        original_tokens = len(content) // 4
        return msg.model_copy(
            update={
                "content": f"[truncated: ~{original_tokens:,} tokens - call tool again if needed] {content[: self.truncate_chars]}...",
                "_truncated": True,
                "_original_tokens": original_tokens,
            }
        )

    def _stub_user_message(self, msg: Message) -> Message:
        """
        Create a stub for a user message to preserve thread while reducing tokens.

        Returns a NEW Message - does not modify the original.
        """
        content = msg.content or ""
        if not isinstance(content, str) or len(content) <= 80:
            return msg  # Too short to stub

        # Take first 50 chars, clean up for display
        preview = content[:50].replace("\n", " ").strip()
        if len(content) > 50:
            preview += "..."

        return msg.model_copy(
            update={
                "content": f'[User message compacted - original: "{preview}"]',
                "_stubbed": True,
                "_original_length": len(content),
            }
        )

    def _format_compaction_notice(self) -> str:
        """
        Format compaction notice based on last compaction stats.

        Returns:
            Formatted notice string, or empty string if no stats available.
        """
        if not self._last_compaction_stats:
            return ""

        stats = self._last_compaction_stats
        level = stats.get("strategy_level", 0)

        # Handle different verbosity levels
        if self.compaction_notice_verbosity == "minimal":
            return (
                '<system-reminder source="context-compaction">\n'
                "Context has been compacted to fit within token budget. "
                "Some older messages and tool results may be truncated.\n"
                "</system-reminder>"
            )

        # Build level-specific affected items (for normal and verbose)
        affected = self._format_affected_items(level, stats)

        # Normal verbosity (default)
        old_count = stats.get("before_messages", 0)
        new_count = stats.get("after_messages", 0)
        removed = stats.get("messages_removed", 0)
        stubbed = stats.get("user_messages_stubbed", 0)
        truncated = stats.get("messages_truncated", 0)
        old_tokens = stats.get("before_tokens", 0)
        new_tokens = stats.get("after_tokens", 0)
        target_tokens = stats.get("target_tokens", 0)
        protected_recent = stats.get("protected_recent", 0.0)
        protected_tool_results = stats.get("protected_tool_results", 0)

        notice = f"""<system-reminder source="context-compaction">
Context has been compacted to fit within token budget.

Compaction summary:
- Strategy level: {level}/8
- Messages: {old_count} → {new_count} ({removed} removed, {stubbed} stubbed)
- Tool results: {truncated} truncated
- Tokens: {old_tokens:,} → {new_tokens:,} (target: {target_tokens:,})

What was preserved:
- All system messages (your instructions and identity)
- Last user message (current task)
- Recent messages ({protected_recent:.0%} of conversation)
- Last {protected_tool_results} tool results (full content)

What may be affected:
{affected}

Note: This compaction is ephemeral (affects only this request). Full history is preserved in session transcript.
</system-reminder>"""

        return notice

    def _format_affected_items(self, level: int, stats: dict[str, Any]) -> str:
        """
        Format affected items based on compaction level.

        Args:
            level: Compaction strategy level (1-8)
            stats: Compaction statistics dictionary

        Returns:
            Formatted string describing what may be affected at this level.
        """
        if level <= 2:
            return (
                '- Older tool results are truncated with "[truncated: ~N tokens]" prefix\n'
                "- You can re-run tools if you need the full output"
            )
        elif level <= 5:
            return (
                '- Older tool results are truncated with "[truncated: ~N tokens]" prefix\n'
                "- Older conversation messages have been removed\n"
                "- You can re-run tools if you need full output"
            )
        else:  # level 6-8
            n = stats.get("protected_tool_results", 5)
            return (
                f"- Most tool results are truncated (except last {n})\n"
                "- Significant conversation history has been removed\n"
                '- Some user messages may be stubbed as "[User message compacted...]"\n'
                "- If context is critical, consider asking user to clarify their current goal"
            )

    def _calculate_budget(self, provider_info: dict[str, Any]) -> int:
        """Calculate effective token budget from provider_info dict or fallback to max_tokens.

        Looks for 'context_window' and 'max_output_tokens' keys in provider_info.
        Falls back to configured max_tokens if not available.
        """
        safety_margin = 4096  # Buffer to avoid hitting hard limits
        output_reserve_fraction = self.output_reserve_fraction

        context_window = provider_info.get("context_window")
        max_output_tokens = provider_info.get("max_output_tokens")

        if context_window and max_output_tokens:
            reserved_output = int(max_output_tokens * output_reserve_fraction)
            budget = context_window - reserved_output - safety_margin
            logger.info(
                f"Budget from provider_info: {budget:,} "
                f"(context={context_window:,}, reserved_output={reserved_output:,} "
                f"[{output_reserve_fraction:.0%} of {max_output_tokens:,}])"
            )
            return budget

        # Fall back to configured max_tokens
        logger.info(f"Using fallback max_tokens budget: {self.max_tokens:,}")
        return self.max_tokens

    def _estimate_tokens(self, messages: list[Message]) -> int:
        """Rough token estimation (chars / 4)."""
        return sum(len(str(msg)) // 4 for msg in messages)
