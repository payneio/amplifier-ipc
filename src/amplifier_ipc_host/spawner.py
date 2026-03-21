"""Sub-session spawning utilities.

Provides helpers for generating child session IDs, merging parent/child
configurations, filtering tools and hooks, enforcing recursion depth limits,
and formatting parent conversation context for child instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4


# ---------------------------------------------------------------------------
# Session ID generation
# ---------------------------------------------------------------------------


def generate_child_session_id(parent_session_id: str, agent_name: str) -> str:
    """Return a child session ID derived from the parent.

    Format: ``{parent_session_id}-{child_span}_{agent_name}``
    where *child_span* is the first 8 hex characters of a random UUID.

    Args:
        parent_session_id: The session ID of the spawning (parent) session.
        agent_name: Name of the child agent being spawned.

    Returns:
        A unique session ID string for the child session.
    """
    child_span = uuid4().hex[:8]
    return f"{parent_session_id}-{child_span}_{agent_name}"


# ---------------------------------------------------------------------------
# Config merging
# ---------------------------------------------------------------------------


def merge_configs(
    parent: dict[str, Any],
    child: dict[str, Any],
) -> dict[str, Any]:
    """Merge parent and child configuration dicts.

    Rules:
    - Scalar values: child overrides parent.
    - List values whose items have a ``name`` key (e.g. tools, hooks):
      merged by name — parent entries are preserved unless the child
      supplies an entry with the same name, in which case the child entry
      wins.  Child-only entries are appended.
    - All other keys: child wins on collision.

    Args:
        parent: Parent session configuration.
        child:  Child session configuration (higher priority).

    Returns:
        A new merged configuration dict.
    """
    result: dict[str, Any] = dict(parent)

    for key, child_value in child.items():
        parent_value = parent.get(key)

        if (
            isinstance(child_value, list)
            and isinstance(parent_value, list)
            and _is_named_list(parent_value)
            and _is_named_list(child_value)
        ):
            result[key] = _merge_named_list(parent_value, child_value)
        else:
            result[key] = child_value

    return result


def _is_named_list(lst: list[Any]) -> bool:
    """Return True when every non-empty item in *lst* is a dict with a 'name' key."""
    return bool(lst) and all(isinstance(item, dict) and "name" in item for item in lst)


def _merge_named_list(
    parent: list[dict[str, Any]],
    child: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge two named-item lists; child entries win on name collision."""
    merged: dict[str, dict[str, Any]] = {item["name"]: item for item in parent}
    for item in child:
        merged[item["name"]] = item
    return list(merged.values())


# ---------------------------------------------------------------------------
# Tool filtering
# ---------------------------------------------------------------------------

_DEFAULT_EXCLUDE_TOOLS = {"delegate"}


def filter_tools(
    tools: list[dict[str, Any]],
    exclude_tools: list[str] | None,
    inherit_tools: list[str] | None,
) -> list[dict[str, Any]]:
    """Filter a list of tool descriptors.

    Priority (highest first):
    1. If *inherit_tools* is provided → allowlist: keep only named tools.
    2. If *exclude_tools* is provided → blocklist: remove named tools.
    3. Default → remove ``'delegate'`` to prevent infinite recursion.

    Args:
        tools:         Full list of tool descriptor dicts (each has a ``name``).
        exclude_tools: Names to remove (blocklist mode).  ``None`` means not set.
        inherit_tools: Names to keep (allowlist mode).  ``None`` means not set.

    Returns:
        Filtered list of tool descriptor dicts.
    """
    if inherit_tools is not None:
        allowed = set(inherit_tools)
        return [t for t in tools if t.get("name") in allowed]

    if exclude_tools is not None:
        blocked = set(exclude_tools)
        return [t for t in tools if t.get("name") not in blocked]

    # Default: exclude 'delegate'
    return [t for t in tools if t.get("name") not in _DEFAULT_EXCLUDE_TOOLS]


# ---------------------------------------------------------------------------
# Hook filtering
# ---------------------------------------------------------------------------


def filter_hooks(
    hooks: list[dict[str, Any]],
    exclude_hooks: list[str] | None,
    inherit_hooks: list[str] | None,
) -> list[dict[str, Any]]:
    """Filter a list of hook descriptors.

    Same pattern as :func:`filter_tools` but with **no** default excludes.

    Priority (highest first):
    1. If *inherit_hooks* is provided → allowlist: keep only named hooks.
    2. If *exclude_hooks* is provided → blocklist: remove named hooks.
    3. Default → return all hooks unchanged.

    Args:
        hooks:         Full list of hook descriptor dicts (each has a ``name``).
        exclude_hooks: Names to remove (blocklist mode).  ``None`` means not set.
        inherit_hooks: Names to keep (allowlist mode).  ``None`` means not set.

    Returns:
        Filtered list of hook descriptor dicts.
    """
    if inherit_hooks is not None:
        allowed = set(inherit_hooks)
        return [h for h in hooks if h.get("name") in allowed]

    if exclude_hooks is not None:
        blocked = set(exclude_hooks)
        return [h for h in hooks if h.get("name") not in blocked]

    # Default: no excludes — return all hooks
    return list(hooks)


# ---------------------------------------------------------------------------
# Recursion depth guard
# ---------------------------------------------------------------------------


def check_self_delegation_depth(
    current_depth: int,
    max_depth: int = 3,
) -> None:
    """Raise ValueError if the self-delegation recursion limit has been reached.

    Args:
        current_depth: Current nesting depth (0-based).
        max_depth:     Maximum allowed depth (default: 3).

    Raises:
        ValueError: When *current_depth* >= *max_depth*.
    """
    if current_depth >= max_depth:
        raise ValueError(
            f"Self-delegation depth limit reached: "
            f"current_depth={current_depth} >= max_depth={max_depth}"
        )


# ---------------------------------------------------------------------------
# Parent context formatting
# ---------------------------------------------------------------------------

_CONVERSATION_ROLES = {"user", "assistant"}


def format_parent_context(
    transcript: list[dict[str, Any]],
    context_depth: str,
    context_scope: str,
    context_turns: int,
) -> str:
    """Format a parent conversation transcript for inclusion in a child instruction.

    Args:
        transcript:     List of message dicts with at least ``role`` and
                        ``content`` keys.
        context_depth:  ``'none'`` — return empty string;
                        ``'recent'`` — include only the last *context_turns*
                        messages (after scope filtering);
                        ``'all'`` — include everything (after scope filtering).
        context_scope:  ``'conversation'`` — keep only ``user`` / ``assistant``
                        messages; any other value keeps all messages.
        context_turns:  Number of messages to keep when *context_depth* is
                        ``'recent'``.

    Returns:
        A formatted string representing the selected portion of the transcript,
        or an empty string when *context_depth* is ``'none'``.
    """
    if context_depth == "none":
        return ""

    # Apply scope filter
    if context_scope == "conversation":
        messages = [m for m in transcript if m.get("role") in _CONVERSATION_ROLES]
    else:
        messages = list(transcript)

    # Apply depth filter
    if context_depth == "recent":
        messages = messages[-context_turns:]

    if not messages:
        return ""

    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SpawnRequest dataclass
# ---------------------------------------------------------------------------


@dataclass
class SpawnRequest:
    """Parameters for spawning a child session.

    Attributes:
        agent:                Agent identifier to spawn (``'self'`` clones the
                              parent config; any other value is a named agent).
        instruction:          The instruction to pass to the child session.
        context_depth:        How much parent context to include: ``'none'``,
                              ``'recent'``, or ``'all'``.
        context_scope:        Which messages to include: ``'conversation'``
                              keeps only user/assistant turns; any other value
                              keeps all messages.
        context_turns:        Number of recent turns to include when
                              *context_depth* is ``'recent'``.
        exclude_tools:        Tool names to remove from the child config
                              (blocklist mode).
        inherit_tools:        Tool names to keep in the child config
                              (allowlist mode).
        exclude_hooks:        Hook names to remove from the child config.
        inherit_hooks:        Hook names to keep in the child config.
        agents:               Agent bundle(s) to make available in the child
                              session.
        provider_preferences: Ordered provider/model preference list.
        model_role:           Override the child agent's default model role.
    """

    agent: str
    instruction: str
    context_depth: str = "none"
    context_scope: str = "conversation"
    context_turns: int | None = None
    exclude_tools: list[str] | None = None
    inherit_tools: list[str] | None = None
    exclude_hooks: list[str] | None = None
    inherit_hooks: list[str] | None = None
    agents: str | list[str] | None = None
    provider_preferences: list[dict[str, Any]] | None = None
    model_role: str | None = None


# ---------------------------------------------------------------------------
# Child session execution (Phase 2 placeholder)
# ---------------------------------------------------------------------------


def _run_child_session(
    child_session_id: str,
    child_config: dict[str, Any],
    instruction: str,
    request: SpawnRequest,
) -> Any:
    """Execute a child session.

    .. note::
        This is a placeholder.  Full implementation is deferred to Phase 2.

    Raises:
        NotImplementedError: Always.
    """
    raise NotImplementedError("Full implementation deferred to Phase 2")


# ---------------------------------------------------------------------------
# spawn_child_session — orchestration entry point
# ---------------------------------------------------------------------------


def spawn_child_session(
    parent_session_id: str,
    parent_config: dict[str, Any],
    transcript: list[dict[str, Any]],
    request: SpawnRequest,
    current_depth: int = 0,
) -> Any:
    """Orchestrate spawning of a child session.

    Steps:
    1. Check self-delegation depth (raises :class:`ValueError` at the limit).
    2. Generate a unique child session ID.
    3. Build the child config: clone parent for ``agent='self'``, else a
       placeholder dict.
    4. Filter tools and hooks according to *request* settings.
    5. Format the parent conversation context.
    6. Build the final instruction with an optional context prefix.
    7. Delegate to :func:`_run_child_session`.

    Args:
        parent_session_id: Session ID of the spawning (parent) session.
        parent_config:     Parent session configuration (tools, hooks, …).
        transcript:        Parent conversation transcript for context
                           extraction.
        request:           Spawn parameters.
        current_depth:     Current self-delegation nesting depth (0-based).

    Returns:
        Whatever :func:`_run_child_session` returns.

    Raises:
        ValueError: When *current_depth* has reached the recursion limit.
    """
    # 1. Enforce recursion depth limit
    check_self_delegation_depth(current_depth)

    # 2. Generate child session ID
    child_session_id = generate_child_session_id(parent_session_id, request.agent)

    # 3. Build child config
    if request.agent == "self":
        child_config: dict[str, Any] = dict(parent_config)
    else:
        child_config = {"agent": request.agent}

    # 4. Filter tools and hooks
    tools: list[dict[str, Any]] = child_config.get("tools", [])
    hooks: list[dict[str, Any]] = child_config.get("hooks", [])
    child_config["tools"] = filter_tools(
        tools, request.exclude_tools, request.inherit_tools
    )
    child_config["hooks"] = filter_hooks(
        hooks, request.exclude_hooks, request.inherit_hooks
    )

    # 5. Format parent context
    context_turns = request.context_turns if request.context_turns is not None else 0
    context_str = format_parent_context(
        transcript,
        request.context_depth,
        request.context_scope,
        context_turns,
    )

    # 6. Build instruction with optional context prefix
    if context_str:
        instruction = f"{context_str}\n\n{request.instruction}"
    else:
        instruction = request.instruction

    # 7. Execute child session (Phase 2 implementation)
    return _run_child_session(child_session_id, child_config, instruction, request)
