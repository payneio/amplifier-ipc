"""Dataclasses and parsing functions for agent/behavior definitions."""

import asyncio
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


async def _fetch_url(url: str) -> str:
    """Fetch a URL and return its content as a UTF-8 string.

    Runs the blocking ``urllib.request.urlopen`` call in a thread-pool executor
    so that the async event loop is not blocked.

    Args:
        url: The HTTP/HTTPS URL to fetch.

    Returns:
        The response body decoded as UTF-8 text.
    """
    loop = asyncio.get_running_loop()

    def _blocking_fetch() -> str:
        with urllib.request.urlopen(url) as response:  # noqa: S310
            return response.read().decode("utf-8")

    return await loop.run_in_executor(None, _blocking_fetch)


@dataclass
class ServiceEntry:
    """Represents the service block from a definition file."""

    stack: str | None = None
    source: str | None = None
    command: str | None = None


@dataclass
class AgentDefinition:
    """Parsed representation of an agent definition YAML file."""

    type: str
    local_ref: str | None = None
    uuid: str | None = None
    version: str | None = None
    description: str | None = None
    orchestrator: str | None = None
    context_manager: str | None = None
    provider: str | None = None
    behaviors: list[str] = field(default_factory=list)
    services: list[ServiceEntry] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    agents: list[str] = field(default_factory=list)
    component_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class BehaviorDefinition:
    """Parsed representation of a behavior definition YAML file."""

    type: str
    local_ref: str | None = None
    uuid: str | None = None
    version: str | None = None
    description: str | None = None
    behaviors: list[str] = field(default_factory=list)
    services: list[ServiceEntry] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedAgent:
    """Resolved agent configuration after merging behaviors into an agent definition."""

    services: list[ServiceEntry] = field(default_factory=list)
    orchestrator: str | None = None
    context_manager: str | None = None
    provider: str | None = None
    component_config: dict[str, Any] = field(default_factory=dict)


def _to_str_list(value: Any) -> list[str]:
    """Coerce a YAML value to a list of strings.

    Handles the formats used in definition files:

    - ``True`` / ``False`` / ``None`` → empty list
    - list of strings → as-is
    - list of single-key dicts (IPC spec format for behaviors)
      e.g. ``[{"modes": "https://..."}]`` → extract the URL values
    - plain dict → extract its values
    """
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, dict):
        return [str(v) for v in value.values()]
    result = []
    for item in value:
        if isinstance(item, dict):
            result.extend(str(v) for v in item.values())
        else:
            result.append(str(item))
    return result


def _to_dict(value: Any) -> dict[str, Any]:
    """Coerce a YAML value to a dict.

    Handles boolean shorthand:
    - ``True``  → empty dict (sentinel meaning "all context")
    - ``False`` → empty dict
    - ``None``  → empty dict
    - dict      → the dict as-is
    """
    if isinstance(value, bool) or value is None or not isinstance(value, dict):
        return {}
    return dict(value)


def _parse_services(services_data: Any) -> list[ServiceEntry]:
    """Parse a list of service dictionaries into ServiceEntry objects.

    Args:
        services_data: Raw YAML data for the services list (list of dicts or None).

    Returns:
        List of ServiceEntry instances. Empty list if services_data is None/empty.
    """
    if not services_data:
        return []
    result = []
    for item in services_data:
        if isinstance(item, dict):
            result.append(
                ServiceEntry(
                    stack=item.get("stack"),
                    source=item.get("source"),
                    command=item.get("command"),
                )
            )
    return result


def parse_agent_definition(
    yaml_content: str,
    path: Path | None = None,
) -> AgentDefinition:
    """Parse a YAML string into an AgentDefinition.

    Args:
        yaml_content: YAML text of an agent definition file.
        path: Optional path to the definition file. When provided, relative
              ``source`` paths in services are resolved against this file's
              parent directory.

    Returns:
        AgentDefinition populated from the YAML content.
    """
    data: dict[str, Any] = yaml.safe_load(yaml_content) or {}
    services = _parse_services(data.get("services"))
    if path is not None:
        for svc in services:
            svc_source = svc.source
            if svc_source and not Path(svc_source).is_absolute():
                svc.source = str((path.parent / svc_source).resolve())
    return AgentDefinition(
        type=data.get("type", "agent"),
        local_ref=data.get("local_ref"),
        uuid=data.get("uuid"),
        version=str(data["version"]) if data.get("version") is not None else None,
        description=data.get("description"),
        orchestrator=data.get("orchestrator"),
        context_manager=data.get("context_manager"),
        provider=data.get("provider"),
        behaviors=_to_str_list(data.get("behaviors")),
        services=services,
        tools=_to_str_list(data.get("tools")),
        hooks=_to_str_list(data.get("hooks")),
        context=_to_dict(data.get("context")),
        agents=_to_str_list(data.get("agents")),
        component_config=_to_dict(data.get("component_config")),
    )


def parse_behavior_definition(yaml_content: str) -> BehaviorDefinition:
    """Parse a YAML string into a BehaviorDefinition.

    Args:
        yaml_content: YAML text of a behavior definition file.

    Returns:
        BehaviorDefinition populated from the YAML content.
    """
    data: dict[str, Any] = yaml.safe_load(yaml_content) or {}
    return BehaviorDefinition(
        type=data.get("type", "behavior"),
        local_ref=data.get("local_ref"),
        uuid=data.get("uuid"),
        version=str(data["version"]) if data.get("version") is not None else None,
        description=data.get("description"),
        behaviors=_to_str_list(data.get("behaviors")),
        services=_parse_services(data.get("services")),
        tools=_to_str_list(data.get("tools")),
        hooks=_to_str_list(data.get("hooks")),
        context=_to_dict(data.get("context")),
    )


async def resolve_agent(
    registry: Any,
    agent_name: str,
    extra_behaviors: list[str] | None = None,
) -> ResolvedAgent:
    """Resolve an agent by walking its behavior tree and collecting services.

    Looks up the agent definition, collects its services, then recursively
    walks the behavior tree collecting and deduplicating services by identity (stack, source, command).

    Args:
        registry: Registry instance used to resolve agent and behavior paths.
        agent_name: The local_ref alias of the agent to resolve.
        extra_behaviors: Optional additional behavior names to merge into the
                         resolved agent after its own behavior tree is walked.

    Returns:
        ResolvedAgent populated with deduplicated services and agent config.

    Raises:
        FileNotFoundError: If the agent is not found in the registry.
    """
    # Step 1: Resolve agent alias to definition file path.
    agent_path = registry.resolve_agent(agent_name)

    # Step 2: Parse agent definition YAML.
    agent_def = parse_agent_definition(agent_path.read_text(), path=agent_path)

    # Step 3: Collect services from agent, keyed by identity for deduplication.
    services_by_key: dict[tuple[str | None, str | None, str | None], ServiceEntry] = {}
    for svc in agent_def.services:
        key = (svc.stack, svc.source, svc.command)
        if key not in services_by_key:
            services_by_key[key] = svc

    visited_behaviors: set[str] = set()

    # Step 4: Inner recursive coroutine that walks one behavior.
    async def _walk_behavior(behavior_name: str) -> None:
        """Resolve a behavior, collect its services, and recurse into nested behaviors.

        When a behavior is not found locally and the name looks like a URL,
        the behavior YAML is fetched, auto-registered (with a ``_meta`` block),
        and the URL is cached as an alias so subsequent calls skip the fetch.
        """
        if behavior_name in visited_behaviors:
            return
        visited_behaviors.add(behavior_name)

        # Attempt to resolve the behavior from the local registry.
        try:
            behavior_path = registry.resolve_behavior(behavior_name)
        except FileNotFoundError:
            if "://" in behavior_name:
                # Fetch the remote behavior and register it locally.
                url = behavior_name
                try:
                    yaml_content = await _fetch_url(url)
                    # register_definition also writes source_url as an alias,
                    # so the next call to resolve_behavior(url) will find it
                    # locally without re-fetching.
                    registry.register_definition(yaml_content, source_url=url)
                    behavior_path = registry.resolve_behavior(url)
                except (OSError, urllib.error.URLError, yaml.YAMLError, ValueError):
                    logger.warning(
                        "Failed to fetch behavior '%s' from URL; skipping.",
                        behavior_name,
                        exc_info=True,
                    )
                    return
            else:
                logger.warning(
                    "Behavior '%s' not found in local registry; skipping.",
                    behavior_name,
                )
                return

        # Parse the behavior definition.
        behavior_def = parse_behavior_definition(behavior_path.read_text())

        # Collect services, deduplicating by identity.
        for svc in behavior_def.services:
            key = (svc.stack, svc.source, svc.command)
            if key not in services_by_key:
                services_by_key[key] = svc

        # Recurse into nested behaviors.
        for nested_behavior in behavior_def.behaviors:
            await _walk_behavior(nested_behavior)

    # Walk the agent's declared behaviors.
    for behavior_name in agent_def.behaviors:
        await _walk_behavior(behavior_name)

    # Step 5: Walk extra_behaviors if provided.
    if extra_behaviors:
        for behavior_name in extra_behaviors:
            await _walk_behavior(behavior_name)

    # Step 6: Return ResolvedAgent.
    return ResolvedAgent(
        services=list(services_by_key.values()),
        orchestrator=agent_def.orchestrator,
        context_manager=agent_def.context_manager,
        provider=agent_def.provider,
        component_config=agent_def.component_config,
    )
