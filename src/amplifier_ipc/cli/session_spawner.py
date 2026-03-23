"""Session spawner — thin bridge for agent delegation in sub-sessions.

When the orchestrator's ``delegate`` tool fires, the CLI intercepts and
creates a child :class:`~amplifier_ipc.host.Host` instance using this
module.
"""

from __future__ import annotations

import uuid
from pydantic import BaseModel, Field
from typing import Any

from amplifier_ipc.host.config import HostSettings, SessionConfig
from amplifier_ipc.host.host import Host


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SpawnRequest(BaseModel):
    """Request to spawn a child agent sub-session.

    Attributes:
        agent_name: The local_ref alias of the child agent to spawn.
        instruction: The instruction/prompt to run in the child session.
        parent_session_id: The session ID of the parent (orchestrator) session.
        context_settings: Optional context propagation settings.
    """

    agent_name: str
    instruction: str
    parent_session_id: str
    context_settings: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------


def generate_sub_session_id(parent_session_id: str, agent_name: str) -> str:
    """Generate a unique sub-session ID derived from the parent and agent name.

    Unsafe characters (spaces, ``/``, ``:``, ``-``) in *agent_name* are
    replaced with underscores, a random 8-hex-character suffix is appended,
    and the result is joined with the parent session ID.

    Args:
        parent_session_id: The ID of the parent session.
        agent_name: The agent name (may contain ``/``, ``:``, ``-``, spaces).

    Returns:
        A string of the form ``"{parent_id}_{safe_name}_{hex8}"``.
    """
    # Replace unsafe characters with underscores
    safe_name = agent_name
    for char in (" ", "/", ":", "-"):
        safe_name = safe_name.replace(char, "_")

    hex8 = uuid.uuid4().hex[:8]
    return f"{parent_session_id}_{safe_name}_{hex8}"


# ---------------------------------------------------------------------------
# Config merging
# ---------------------------------------------------------------------------


def merge_child_config(
    parent: SessionConfig,
    child_services: list[str],
    *,
    orchestrator: str | None = None,
    context_manager: str | None = None,
    provider: str | None = None,
    component_config: dict[str, Any] | None = None,
) -> SessionConfig:
    """Merge parent config with child agent overrides into a new SessionConfig.

    Services from both parent and child are combined, preserving order and
    deduplicating by name (first occurrence wins).  ``component_config`` is
    merged with the parent as the base and child values overriding.  All
    other fields (orchestrator, context_manager, provider) fall back to the
    parent values when not explicitly overridden by the child.

    Args:
        parent: The parent session's :class:`~amplifier_ipc.host.config.SessionConfig`.
        child_services: Additional service names required by the child agent.
        orchestrator: Optional orchestrator override for the child session.
        context_manager: Optional context_manager override for the child session.
        provider: Optional provider override for the child session.
        component_config: Optional component_config override (merged on top of parent).

    Returns:
        A new :class:`~amplifier_ipc.host.config.SessionConfig` for the child session.
    """
    # Deduplicate services: parent first, then child additions
    seen: set[str] = set()
    merged_services: list[str] = []
    for svc in list(parent.services) + list(child_services):
        if svc not in seen:
            seen.add(svc)
            merged_services.append(svc)

    # Merge component_config: parent base, child overrides on top
    merged_component_config: dict[str, Any] = dict(parent.component_config)
    if component_config:
        merged_component_config.update(component_config)

    return SessionConfig(
        services=merged_services,
        orchestrator=orchestrator if orchestrator is not None else parent.orchestrator,
        context_manager=context_manager
        if context_manager is not None
        else parent.context_manager,
        provider=provider if provider is not None else parent.provider,
        component_config=merged_component_config,
    )


# ---------------------------------------------------------------------------
# Sub-session spawning
# ---------------------------------------------------------------------------


async def spawn_sub_session(
    *,
    request: SpawnRequest,
    parent_config: SessionConfig,
    registry: Any,
    settings: HostSettings | None = None,
    event_handler: Any = None,
    nesting_depth: int = 0,
) -> str:
    """Spawn a child agent sub-session and return its response.

    Resolves the child agent from the registry, builds its :class:`SessionConfig`,
    merges it with the parent config, creates a :class:`Host` instance, runs
    it with the given instruction, and returns the final response text from
    the :class:`~amplifier_ipc.host.events.CompleteEvent`.

    Args:
        request: The :class:`SpawnRequest` describing what to spawn.
        parent_config: The parent session's :class:`SessionConfig` to merge from.
        registry: The :class:`~amplifier_ipc.cli.registry.Registry` used for
            agent resolution.
        settings: Optional :class:`HostSettings` for the child Host.  Defaults
            to a new :class:`HostSettings` if not provided.
        event_handler: Optional callable invoked with each event from the child
            session (for streaming/UI integration).  Currently unused.
        nesting_depth: Nesting level for sub-sub-sessions (informational).

    Returns:
        The response string from the child agent's
        :class:`~amplifier_ipc.host.events.CompleteEvent`.

    Raises:
        RuntimeError: If the child session completes without emitting a
            :class:`~amplifier_ipc.host.events.CompleteEvent`.
    """
    from amplifier_ipc.host.definitions import resolve_agent
    from amplifier_ipc.cli.session_launcher import build_session_config
    from amplifier_ipc.host.events import CompleteEvent

    # Resolve child agent definition
    child_resolved = await resolve_agent(registry, request.agent_name)

    # Build SessionConfig from child agent
    child_config = build_session_config(child_resolved)

    # Merge child config with parent
    merged_config = merge_child_config(
        parent_config,
        child_services=child_config.services,
        orchestrator=child_config.orchestrator or None,
        context_manager=child_config.context_manager or None,
        provider=child_config.provider or None,
        component_config=child_config.component_config or None,
    )

    # Create Host instance
    host_settings = settings if settings is not None else HostSettings()
    host = Host(merged_config, host_settings)

    # Run the child session, collecting the complete response
    response: str = ""
    async for event in host.run(request.instruction):
        if isinstance(event, CompleteEvent):
            response = event.result
            break

    return response
