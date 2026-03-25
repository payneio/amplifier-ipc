"""Sub-session spawning utilities.

Provides helpers for generating child session IDs, merging parent/child
configurations, filtering tools and hooks, enforcing recursion depth limits,
and formatting parent conversation context for child instructions.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Session ID generation
# ---------------------------------------------------------------------------

_SPAN_HEX_LEN = 16
_DEFAULT_PARENT_SPAN = "0" * _SPAN_HEX_LEN
_SPAN_PATTERN = re.compile(r"^([0-9a-f]{16})-([0-9a-f]{16})_")
_AGENT_NAME_CLEANUP = re.compile(r"[^a-z0-9]+")


def generate_child_session_id(parent_session_id: str, agent_name: str) -> str:
    """Return a child session ID derived from the parent (W3C Trace Context format).

    Format: ``{parent_span}-{child_span}_{sanitized_agent_name}``

    * When the parent is a root UUID (no span pattern match), *parent_span* is
      ``0000000000000000`` (zero sentinel).
    * When the parent is itself a child session matching the span pattern,
      the parent's *child_span* is promoted to become the new *parent_span*.

    Agent name sanitization: lowercase, non-alphanumeric characters replaced
    with hyphens (multiple consecutive non-alphanum collapsed to one hyphen),
    leading dots/hyphens stripped; defaults to ``"agent"`` if the result is empty.

    Args:
        parent_session_id: The session ID of the spawning (parent) session.
        agent_name: Name of the child agent being spawned.

    Returns:
        A unique session ID string for the child session.
    """
    # Determine parent_span from parent session ID
    match = _SPAN_PATTERN.match(parent_session_id)
    if match:
        # Parent is already a child session — promote its child_span
        parent_span = match.group(2)
    else:
        # Parent is a root UUID — use zero sentinel
        parent_span = _DEFAULT_PARENT_SPAN

    # Sanitize agent name
    sanitized = agent_name.lower()
    sanitized = _AGENT_NAME_CLEANUP.sub("-", sanitized)
    sanitized = sanitized.strip("-.")
    if not sanitized:
        sanitized = "agent"

    # Generate a fresh child span
    child_span = uuid4().hex[:_SPAN_HEX_LEN]

    return f"{parent_span}-{child_span}_{sanitized}"


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
# SpawnRequest
# ---------------------------------------------------------------------------


class SpawnRequest(BaseModel):
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


async def _run_child_session(
    child_session_id: str,
    child_config: dict[str, Any],
    instruction: str,
    request: SpawnRequest,
    settings: Any | None = None,
    session_dir: Any | None = None,
    service_configs: dict[str, Any] | None = None,
    shared_services: dict[str, Any] | None = None,
    shared_registry: Any | None = None,
    event_callback: Any | None = None,
    spawn_depth: int = 0,
) -> dict[str, Any]:
    """Execute a child session by creating and running a child Host.

    When *shared_services* and *shared_registry* are provided the child Host
    skips spawning new service processes and reuses the parent's already-running
    ones.  This is the normal path for delegate/spawn — the parent passes its
    ``_services`` dict and ``_registry`` so the child can start immediately
    without the overhead (and potential failure) of re-spawning every service.

    Args:
        child_session_id: The pre-generated ID for this child session.
        child_config: Configuration dict for the child session (may contain
            services, orchestrator, context_manager, provider keys).
        instruction: The instruction to pass to the child Host.
        request: The original spawn request parameters.
        settings: Optional :class:`~amplifier_ipc.host.config.HostSettings`;
            a default instance is created when ``None``.
        session_dir: Optional session directory path forwarded to :class:`Host`.
        service_configs: Optional per-service component config dicts.
        shared_services: Parent's running service processes.  When supplied
            the child Host will not spawn or tear down services.
        shared_registry: Parent's :class:`~amplifier_ipc.host.service_index.ServiceIndex`.
            When supplied the child Host skips the ``describe``/``configure``
            discovery phase.

    Returns:
        A dict with keys:

        * ``session_id``: The child session ID.
        * ``response``: The text result from the final
          :class:`~amplifier_ipc.host.events.CompleteEvent`, or ``""`` if
          none was emitted.
        * ``turn_count``: Number of :class:`~amplifier_ipc.host.events.CompleteEvent`
          instances received (0 or 1).
        * ``metadata``: Reserved dict for future use.
    """
    # Lazy imports to avoid the circular dependency:
    # host.py → spawner.py (spawn_child_session)
    # spawner.py → host.py (Host)
    from amplifier_ipc.host.config import HostSettings, SessionConfig  # noqa: PLC0415
    from amplifier_ipc.host.events import CompleteEvent  # noqa: PLC0415
    from amplifier_ipc.host.host import Host  # noqa: PLC0415

    # 1. Build SessionConfig from child_config dict
    session_config = SessionConfig(
        services=child_config.get("services", []),
        orchestrator=child_config.get("orchestrator", ""),
        context_manager=child_config.get("context_manager", ""),
        provider=child_config.get("provider", ""),
        component_config=child_config.get("component_config", {}),
    )

    # 2. Create HostSettings if not provided
    host_settings: HostSettings = settings if settings is not None else HostSettings()

    # 3. Create Host instance — pass shared services/registry when available so
    #    the child skips spawning new processes and describe/configure discovery.
    host = Host(
        session_config,
        host_settings,
        session_dir,
        service_configs=service_configs,
        shared_services=shared_services,
        shared_registry=shared_registry,
        spawn_depth=spawn_depth,
    )

    # 4. Run the host, iterating async events, collecting CompleteEvent response
    response = ""
    turn_count = 0
    async for event in host.run(instruction):
        if event_callback is not None:
            event_callback(event)
        if isinstance(event, CompleteEvent):
            response = event.result
            turn_count += 1

    # 5. Return result dict
    return {
        "session_id": child_session_id,
        "response": response,
        "turn_count": turn_count,
        "metadata": {"agent": request.agent},
    }


# ---------------------------------------------------------------------------
# spawn_child_session — orchestration entry point
# ---------------------------------------------------------------------------


async def spawn_child_session(
    parent_session_id: str,
    parent_config: dict[str, Any],
    transcript: list[dict[str, Any]],
    request: SpawnRequest,
    current_depth: int = 0,
    settings: Any | None = None,
    service_configs: dict[str, Any] | None = None,
    shared_services: dict[str, Any] | None = None,
    shared_registry: Any | None = None,
    event_callback: Any | None = None,
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
        settings:          Optional :class:`~amplifier_ipc.host.config.HostSettings`.
        service_configs:   Optional per-service component config dicts.
        shared_services:   Parent's running service processes.  When provided
                           the child Host skips spawning new processes.
        shared_registry:   Parent's service index.  When provided the
                           child Host skips ``describe``/``configure`` discovery.

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
    # Always clone the parent config so the child inherits orchestrator,
    # context_manager, provider, and services.  Non-self agents may
    # override specific fields in the future via agent definitions.
    child_config: dict[str, Any] = dict(parent_config)

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
    if request.context_depth == "recent" and request.context_turns is None:
        raise ValueError("context_turns must be set when context_depth='recent'")
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

    # 7. Execute child session — propagate depth so the child Host
    #    enforces the self-delegation limit at the correct nesting level.
    child_depth = current_depth + 1 if request.agent == "self" else 0
    return await _run_child_session(
        child_session_id,
        child_config,
        instruction,
        request,
        settings=settings,
        service_configs=service_configs,
        shared_services=shared_services,
        shared_registry=shared_registry,
        event_callback=event_callback,
        spawn_depth=child_depth,
    )
