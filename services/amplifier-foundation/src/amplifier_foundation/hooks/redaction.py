"""Redaction hook — masks secrets/PII in event data for logging."""

from __future__ import annotations

import logging
import re
from collections.abc import Set as AbstractSet
from typing import Any

from amplifier_ipc.protocol import hook
from amplifier_ipc.protocol.models import HookAction, HookResult

logger = logging.getLogger(__name__)

SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS Access Key
    re.compile(
        r"(?:xox[abpr]-[A-Za-z0-9-]+|AIza[0-9A-Za-z-_]{35})"
    ),  # Slack/Google keys
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
]
PII_PATTERNS = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\+?\d[\d\s().-]{7,}\d"),
]

# ---------------------------------------------------------------------------
# Default allowlist — structural event fields that must never be redacted.
#
# WHAT: These are infrastructure/envelope fields used for session correlation,
#       lineage tracking, event ordering, and trace identification.
#
# WHY:  Two PII regex patterns produce systematic false positives on these
#       structural fields:
#
#       1. Phone regex  \+?\d[\d\s().-]{7,}\d  matches ISO timestamps
#          (e.g. "2026-02-20T14:30:00Z" → "2026-02-20" triggers the pattern)
#          and numeric runs inside UUIDs (e.g. "446655440000" inside
#          "550e8400-e29b-41d4-a716-446655440000"). Every event carries a
#          timestamp from the kernel's emit(), so without the allowlist every
#          event's timestamp is replaced with [REDACTED:PII].
#
#       2. Email regex  [A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}
#          can match username fragments when project slugs derived from
#          filesystem paths (e.g. /home/user/my.project) carry dot-separated
#          segments into event fields that happen to resemble local-part@domain.
#
#       Together these cause critical identifiers to display as [REDACTED:PII],
#       breaking event correlation, session lineage trees, and trace
#       verification.
#
# HOW:  These defaults are merged (union) with user-provided
#       config["allowlist"] entries at mount() time. Users extend but never
#       replace the defaults.
# ---------------------------------------------------------------------------
DEFAULT_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Infrastructure envelope — present on every event via emit().
        # session_id and parent_id are the primary keys for event correlation
        # and session lineage.
        "session_id",
        "parent_id",
        "timestamp",
        # Session lineage — parent ID in session:fork events
        "parent",
        # Event classification
        "lvl",
        "level",
        # Correlation identifiers — join related events across the lifecycle
        "tool_name",
        "provider",
        "orchestrator",
        "status",
        # Streaming envelope
        "type",
        "ts",
        "seq",
        "turn_id",
        "span_id",
        "parent_span_id",
    }
)

# Events whose data feeds back into LLM context — skip redaction to avoid
# corrupting tool results the model needs verbatim (session IDs, timestamps).
_CONTEXT_EVENTS = frozenset({"tool:pre", "tool:post"})

# Events subscribed to by this hook
_HOOK_EVENTS = [
    "session:start",
    "session:end",
    "prompt:submit",
    "prompt:complete",
    "plan:start",
    "plan:end",
    "provider:request",
    "provider:response",
    "provider:error",
    "tool:pre",
    "tool:post",
    "tool:error",
    "context:pre_compact",
    "context:post_compact",
    "artifact:write",
    "artifact:read",
    "policy:violation",
    "approval:required",
    "approval:granted",
    "approval:denied",
]


def _mask_text(s: str, rules: list[str]) -> str:
    out = s
    if "secrets" in rules:
        for pat in SECRET_PATTERNS:
            out = pat.sub("[REDACTED:SECRET]", out)
    if "pii-basic" in rules:
        for pat in PII_PATTERNS:
            out = pat.sub("[REDACTED:PII]", out)
    return out


def _scrub(
    obj: Any, rules: list[str], allowlist: AbstractSet[str], path: str = ""
) -> Any:
    if path in allowlist:
        return obj
    if isinstance(obj, str):
        return _mask_text(obj, rules)
    if isinstance(obj, list):
        return [_scrub(v, rules, allowlist, f"{path}[{i}]") for i, v in enumerate(obj)]
    if isinstance(obj, dict):
        return {
            k: _scrub(v, rules, allowlist, f"{path}.{k}" if path else k)
            for k, v in obj.items()
        }
    return obj


@hook(events=_HOOK_EVENTS, priority=10)
class RedactionHook:
    """Masks secrets and PII in event data for logging purposes.

    Uses MODIFY to return redacted copies rather than mutating the shared
    event data dict in-place. Skips context-feeding events (tool:pre,
    tool:post) to avoid corrupting tool results the model needs verbatim.
    """

    name = "redaction"
    events = _HOOK_EVENTS
    priority = 10

    def __init__(self) -> None:
        self.rules: list[str] = ["secrets", "pii-basic"]
        self.allowlist: frozenset[str] = DEFAULT_ALLOWLIST

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Scrub secrets/PII from event data, skipping context-feeding events."""
        if event in _CONTEXT_EVENTS:
            return HookResult(action=HookAction.CONTINUE)

        try:
            redacted = _scrub(data, self.rules, self.allowlist)
            if isinstance(redacted, dict):
                redacted["redaction"] = {"applied": True, "rules": self.rules}
                return HookResult(action=HookAction.MODIFY, data=redacted)
        except Exception as exc:
            logger.warning(
                "Redaction failed for event %s — data returned unredacted: %s",
                event,
                exc,
            )

        return HookResult(action=HookAction.CONTINUE)
