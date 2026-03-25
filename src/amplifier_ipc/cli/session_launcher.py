"""Session launcher — bridges definition resolution and Host creation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from amplifier_ipc.host.config import (
    HostSettings,
    ServiceOverride,
    SessionConfig,
    load_settings,
)
from amplifier_ipc.host.host import Host

from amplifier_ipc.cli.commands.install import install_service
from amplifier_ipc.cli.provider_env_detect import detect_provider_from_env
from amplifier_ipc.cli.settings import get_settings
from amplifier_ipc.host.definition_registry import Registry
from amplifier_ipc.host.definitions import ResolvedAgent, ServiceEntry, resolve_agent

logger = logging.getLogger(__name__)


def build_session_config(resolved: ResolvedAgent) -> SessionConfig:
    """Build a SessionConfig from a ResolvedAgent.

    Maps the resolved agent's service refs (from ``(ref, ServiceEntry)`` tuples),
    orchestrator, context_manager, provider, and component_config to a
    SessionConfig suitable for the Host.

    Args:
        resolved: A fully resolved agent configuration.

    Returns:
        SessionConfig populated from the resolved agent fields.
    """
    return SessionConfig(
        services=[ref for ref, _svc in resolved.services],
        orchestrator=resolved.orchestrator or "",
        context_manager=resolved.context_manager or "",
        provider=resolved.provider or "",
        component_config=resolved.component_config,
    )


def _build_service_overrides(
    services: list[tuple[str, ServiceEntry]],
    existing_overrides: dict[str, ServiceOverride],
    registry: Registry,
    definition_ids: dict[str, str],
) -> dict[str, ServiceOverride]:
    """Build ServiceOverride entries for services that have a command.

    For each service with a non-empty ``command`` field, creates a
    ``ServiceOverride`` keyed by the service ref.  Services already covered by
    *existing_overrides* are left unchanged (settings file takes priority).

    When a service has an installed environment (via ``registry`` and
    ``definition_ids``), the command is resolved to the full path inside
    the environment's ``bin/`` directory so it can be found without being
    on the system PATH.

    Args:
        services: Resolved service entries as ``(ref, ServiceEntry)`` tuples.
        existing_overrides: Overrides already loaded from settings files.
        registry: Registry instance used to locate installed environments.
        definition_ids: Mapping of service ref to definition_id.

    Returns:
        A merged dict of service overrides: existing_overrides plus any new
        command-based entries (settings overrides take priority on conflict).
    """
    merged: dict[str, ServiceOverride] = dict(existing_overrides)

    for ref, svc in services:
        if ref not in merged and svc.command:
            command = svc.command
            # Resolve to the full path inside the installed environment
            # so the binary can be found without being on PATH.
            definition_id = definition_ids.get(ref)
            if definition_id and registry.is_installed(definition_id):
                env_bin = registry.get_environment_path(definition_id) / "bin" / command
                if env_bin.exists():
                    command = str(env_bin)
            merged[ref] = ServiceOverride(command=[command], working_dir=None)

    return merged


def _resolve_provider_config(
    config: SessionConfig,
    resolved: ResolvedAgent,
) -> SessionConfig:
    """Apply CLI settings and auto-detection to resolve the effective provider.

    Resolution order (first non-empty wins):
    1. CLI persistent settings (``amplifier-ipc provider use <name>``)
    2. Agent definition (``provider:`` field)
    3. Auto-detection from environment variables

    Additionally merges ``provider_overrides`` from CLI settings (model, etc.)
    into ``resolved.service_configs`` so they reach the provider service via
    the ``configure`` wire method.

    Args:
        config: The session config built from the resolved agent.
        resolved: The fully resolved agent with mutable ``service_configs``.

    Returns:
        A (possibly updated) SessionConfig with the effective provider set.
    """
    cli_settings = get_settings()
    effective_provider = config.provider

    # 1. CLI persistent settings override definition
    settings_provider = cli_settings.get_provider()
    if settings_provider:
        effective_provider = settings_provider

    # 2. Auto-detect from environment if nothing is configured
    if not effective_provider:
        detected = detect_provider_from_env()
        if detected:
            provider_name, env_var = detected
            # Normalize hyphen names to underscore (azure-openai -> azure_openai)
            effective_provider = provider_name.replace("-", "_")
            logger.info(
                "Auto-detected provider '%s' from %s", effective_provider, env_var
            )

    # 3. Merge provider_overrides from CLI settings into service_configs
    settings_overrides = cli_settings.get_provider_overrides()
    if settings_overrides and effective_provider:
        override_config: dict[str, Any] = {}
        for entry in settings_overrides:
            if entry.get("provider") == effective_provider:
                # Collect all keys except "provider" (e.g., model, max_tokens)
                for k, v in entry.items():
                    if k != "provider":
                        override_config[k] = v
                break

        if override_config:
            # Broadcast to all services.  The server's handle_configure()
            # matches by component name, so unmatched keys are ignored.
            for ref, _svc in resolved.services:
                svc_cfg = resolved.service_configs.get(ref, {})
                existing = svc_cfg.get(effective_provider, {})
                if not isinstance(existing, dict):
                    existing = {}
                svc_cfg[effective_provider] = {**existing, **override_config}
                resolved.service_configs[ref] = svc_cfg

    # Return updated config if provider changed
    if effective_provider != config.provider:
        return SessionConfig(
            services=config.services,
            orchestrator=config.orchestrator,
            context_manager=config.context_manager,
            provider=effective_provider,
            component_config=config.component_config,
        )
    return config


def list_registered_agents(registry: Registry | None = None) -> list[str]:
    """Return the list of registered agent ref names from the registry.

    Reads ``agents.yaml`` from the registry home directory and returns all
    alias keys that are not URL-based (i.e. do not contain ``://``).

    Args:
        registry: Optional Registry instance.  If ``None``, a new Registry is
                  created using the default AMPLIFIER_HOME path.

    Returns:
        A list of agent ref name strings (may be empty if none are registered
        or if the alias file cannot be read).
    """
    if registry is None:
        registry = Registry()

    agents_yaml = registry.home / "agents.yaml"
    if not agents_yaml.exists():
        return []

    try:
        alias_data = yaml.safe_load(agents_yaml.read_text()) or {}
    except Exception:  # noqa: BLE001
        return []

    # Filter out URL-based aliases (contain "://") — those are source aliases
    # registered alongside the canonical ref during discover/register.
    return [k for k in alias_data if "://" not in str(k)]


async def launch_session(
    agent_name: str,
    extra_behaviors: list[str] | None = None,
    registry: Registry | None = None,
    user_settings_path: Path | None = None,
    project_settings_path: Path | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    max_tokens: int | None = None,
    verbose: bool = False,
    working_dir: Path | None = None,
) -> Host:
    """Resolve an agent definition and create a Host ready to run a session.

    1. Creates a Registry from AMPLIFIER_HOME if one is not provided.
    2. Calls resolve_agent() to walk the behavior tree and collect services.
    3. Builds a SessionConfig from the resolved agent.
    4. Resolves the effective provider (CLI settings > definition > auto-detect).
    5. Applies any CLI-level ``provider_override`` (highest priority).
    6. Merges provider overrides from CLI settings and ``model_override`` /
       ``max_tokens`` into service_configs.
    7. Loads HostSettings from the standard settings files (user + project).
    8. Builds service overrides for any service with a ``command:`` field,
       adding them to HostSettings so the Host can spawn them via a custom
       command without requiring hardcoded settings.yaml entries.
    9. Returns a Host constructed with the config, settings, and service_configs.

    Args:
        agent_name: The ref alias of the agent to launch.
        extra_behaviors: Optional additional behavior names to merge into the
                         resolved agent after its own behavior tree is walked.
        registry: Optional Registry instance. If None, a new Registry is
                  created using the default AMPLIFIER_HOME path.
        user_settings_path: Path to the user-level settings YAML file.
                             Defaults to ``~/.amplifier/settings.yaml``.
        project_settings_path: Path to the project-level settings YAML file.
                                Defaults to ``.amplifier/settings.yaml`` in
                                the current working directory.
        provider_override: If set, overrides the resolved provider with this
                           value (highest priority — wins over CLI settings and
                           auto-detection).
        model_override: If set, injects a ``model`` key into the provider
                        section of ``service_configs`` for each service so the
                        orchestrator can pass it to the provider at runtime.
                        TODO: add a dedicated ``model`` field to SessionConfig
                        and thread it through the Host/orchestrator natively.
        max_tokens: If set, injects ``max_tokens`` into the provider section of
                    ``service_configs``.  Same TODO as ``model_override``.
        verbose: When True, print additional session setup detail (resolved
                 services, applied overrides) to stdout.

    Returns:
        A Host instance configured from the resolved agent definition.
    """
    if registry is None:
        registry = Registry()

    resolved = await resolve_agent(registry, agent_name, extra_behaviors)

    # Lazy install: for each service that has a source but no installed environment,
    # run the install step automatically so the user doesn't have to run it manually.
    for ref, svc in resolved.services:
        definition_id = resolved.definition_ids.get(ref)
        if definition_id and svc.source and not registry.is_installed(definition_id):
            print(f"Installing service {ref}...")  # noqa: T201
            install_service(registry, definition_id, svc.source)

    config = build_session_config(resolved)

    # Resolve provider: CLI settings > definition > auto-detect.
    # Also merges provider_overrides into service_configs.
    config = _resolve_provider_config(config, resolved)

    if verbose:
        logger.info(
            "Resolved agent '%s' with provider '%s'", agent_name, config.provider
        )
        print(f"Resolved agent: {agent_name}")  # noqa: T201
        for ref, _svc in resolved.services:
            print(f"  Service: {ref}")  # noqa: T201

    # ---- Apply per-run CLI overrides (highest priority) ------------------
    # provider_override supersedes everything including CLI persistent settings.
    if provider_override:
        config = SessionConfig(
            services=config.services,
            orchestrator=config.orchestrator,
            context_manager=config.context_manager,
            provider=provider_override,
            component_config=config.component_config,
        )
        if verbose:
            print(f"  Provider override: {provider_override}")  # noqa: T201

    # model_override and max_tokens are threaded through service_configs keyed
    # by the effective provider name, because SessionConfig has no dedicated
    # fields for them yet.
    # TODO: add `model` and `max_tokens` fields to SessionConfig and thread
    # them through the Host/orchestrator provider resolution path natively.
    if model_override is not None or max_tokens is not None:
        effective_provider = config.provider
        for ref, _svc in resolved.services:
            svc_cfg = resolved.service_configs.get(ref, {})
            provider_cfg: dict[str, Any] = dict(svc_cfg.get(effective_provider, {}))
            if model_override is not None:
                provider_cfg["model"] = model_override
            if max_tokens is not None:
                provider_cfg["max_tokens"] = max_tokens
            svc_cfg[effective_provider] = provider_cfg
            resolved.service_configs[ref] = svc_cfg
        if verbose and model_override is not None:
            print(f"  Model override: {model_override}")  # noqa: T201
        if verbose and max_tokens is not None:
            print(f"  Max tokens: {max_tokens}")  # noqa: T201

    # Load settings from the standard locations (silently skips missing files).
    # Pass agent_name so load_settings can extract nested agent-scoped overrides
    # from the new settings.yaml format:
    #   amplifier_ipc.service_overrides.<agent_name>.<service_ref>: {command, ...}
    effective_user_path = user_settings_path or (
        Path.home() / ".amplifier" / "settings.yaml"
    )
    effective_project_path = project_settings_path or (
        Path.cwd() / ".amplifier" / "settings.yaml"
    )
    settings = load_settings(
        user_settings_path=effective_user_path,
        project_settings_path=effective_project_path,
        agent_name=agent_name,
    )

    # Build service overrides for source-based services.
    # Settings file overrides take priority (they are passed as existing_overrides).
    merged_overrides = _build_service_overrides(
        resolved.services, settings.service_overrides, registry, resolved.definition_ids
    )
    settings = HostSettings(service_overrides=merged_overrides)

    return Host(
        config,
        settings,
        service_configs=resolved.service_configs,
        working_dir=working_dir,
    )
