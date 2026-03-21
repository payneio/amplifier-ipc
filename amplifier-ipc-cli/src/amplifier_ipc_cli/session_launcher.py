"""Session launcher — bridges definition resolution and Host creation."""

from __future__ import annotations

from amplifier_ipc_host.config import HostSettings, SessionConfig
from amplifier_ipc_host.host import Host

from amplifier_ipc_cli.definitions import ResolvedAgent, resolve_agent
from amplifier_ipc_cli.registry import Registry


def build_session_config(resolved: ResolvedAgent) -> SessionConfig:
    """Build a SessionConfig from a ResolvedAgent.

    Maps the resolved agent's service names, orchestrator, context_manager,
    provider, and component_config to a SessionConfig suitable for the Host.

    Args:
        resolved: A fully resolved agent configuration.

    Returns:
        SessionConfig populated from the resolved agent fields.
    """
    return SessionConfig(
        services=[svc.name for svc in resolved.services],
        orchestrator=resolved.orchestrator or "",
        context_manager=resolved.context_manager or "",
        provider=resolved.provider or "",
        component_config=resolved.component_config,
    )


async def launch_session(
    agent_name: str,
    extra_behaviors: list[str] | None = None,
    registry: Registry | None = None,
) -> Host:
    """Resolve an agent definition and create a Host ready to run a session.

    1. Creates a Registry from AMPLIFIER_HOME if one is not provided.
    2. Calls resolve_agent() to walk the behavior tree and collect services.
    3. Builds a SessionConfig from the resolved agent.
    4. Creates a default HostSettings.
    5. Returns a Host constructed with the config and settings.

    Args:
        agent_name: The local_ref alias of the agent to launch.
        extra_behaviors: Optional additional behavior names to merge into the
                         resolved agent after its own behavior tree is walked.
        registry: Optional Registry instance. If None, a new Registry is
                  created using the default AMPLIFIER_HOME path.

    Returns:
        A Host instance configured from the resolved agent definition.
    """
    if registry is None:
        registry = Registry()

    resolved = await resolve_agent(registry, agent_name, extra_behaviors)
    config = build_session_config(resolved)
    settings = HostSettings()
    return Host(config, settings)
