"""Session launcher — bridges definition resolution and Host creation."""

from __future__ import annotations

from pathlib import Path

from amplifier_ipc_host.config import SessionConfig, load_settings
from amplifier_ipc_host.host import Host

from amplifier_ipc_host.definition_registry import Registry
from amplifier_ipc_host.definitions import ResolvedAgent, resolve_agent


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
    user_settings_path: Path | None = None,
    project_settings_path: Path | None = None,
) -> Host:
    """Resolve an agent definition and create a Host ready to run a session.

    1. Creates a Registry from AMPLIFIER_HOME if one is not provided.
    2. Calls resolve_agent() to walk the behavior tree and collect services.
    3. Builds a SessionConfig from the resolved agent.
    4. Loads HostSettings from the standard settings files (user + project).
    5. Returns a Host constructed with the config and settings.

    Args:
        agent_name: The local_ref alias of the agent to launch.
        extra_behaviors: Optional additional behavior names to merge into the
                         resolved agent after its own behavior tree is walked.
        registry: Optional Registry instance. If None, a new Registry is
                  created using the default AMPLIFIER_HOME path.
        user_settings_path: Path to the user-level settings YAML file.
                             Defaults to ``~/.amplifier/settings.yaml``.
        project_settings_path: Path to the project-level settings YAML file.
                                Defaults to ``.amplifier/settings.yaml`` in
                                the current working directory.

    Returns:
        A Host instance configured from the resolved agent definition.
    """
    if registry is None:
        registry = Registry()

    resolved = await resolve_agent(registry, agent_name, extra_behaviors)
    config = build_session_config(resolved)

    # Load settings from the standard locations (silently skips missing files).
    effective_user_path = user_settings_path or (
        Path.home() / ".amplifier" / "settings.yaml"
    )
    effective_project_path = project_settings_path or (
        Path.cwd() / ".amplifier" / "settings.yaml"
    )
    settings = load_settings(
        user_settings_path=effective_user_path,
        project_settings_path=effective_project_path,
    )

    return Host(config, settings)
