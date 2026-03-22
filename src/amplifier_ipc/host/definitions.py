"""Dataclasses and parsing functions for agent/behavior definitions."""

import asyncio
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
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

    ref: str | None = None
    uuid: str | None = None
    version: str | None = None
    description: str | None = None
    orchestrator: str | None = None
    context_manager: str | None = None
    provider: str | None = None
    tools: bool = False
    hooks: bool = False
    agents: bool = False
    context: bool = False
    behaviors: list[dict[str, str]] = field(default_factory=list)
    service: ServiceEntry | None = None
    component_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class BehaviorDefinition:
    """Parsed representation of a behavior definition YAML file."""

    ref: str | None = None
    uuid: str | None = None
    version: str | None = None
    description: str | None = None
    tools: bool = False
    hooks: bool = False
    context: bool = False
    behaviors: list[dict[str, str]] = field(default_factory=list)
    service: ServiceEntry | None = None
    component_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedAgent:
    """Resolved agent configuration after merging behaviors into an agent definition."""

    services: list[ServiceEntry] = field(default_factory=list)
    orchestrator: str | None = None
    context_manager: str | None = None
    provider: str | None = None
    component_config: dict[str, Any] = field(default_factory=dict)


def _to_bool(value: Any) -> bool:
    """Coerce a YAML value to a bool capability flag.

    - ``True`` / ``False``        → as-is
    - ``None``                    → False
    - non-empty list / dict / str → True (capability is enabled)
    - empty list / dict / str     → False
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return bool(value)


def _to_behavior_list(value: Any) -> list[dict[str, str]]:
    """Coerce a YAML value to a list of ``{alias: ref}`` dicts.

    Handles the formats used in definition files:

    - ``True`` / ``False`` / ``None`` → empty list
    - list of ``{alias: url}`` dicts  → as-is
    - list of plain strings           → each wrapped as ``{"ref": string}``
    - plain dict                      → wrapped as a single-element list
    """
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, dict):
        return [{k: str(v)} for k, v in value.items()]
    result: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            result.append({k: str(v) for k, v in item.items()})
        else:
            result.append({"ref": str(item)})
    return result


def _parse_service(service_data: Any) -> ServiceEntry | None:
    """Parse a service dict into a ServiceEntry.

    Args:
        service_data: Raw YAML value for the ``service:`` key.

    Returns:
        A ``ServiceEntry`` when given a dict, otherwise ``None``.
    """
    if not isinstance(service_data, dict):
        return None
    return ServiceEntry(
        stack=service_data.get("stack"),
        source=service_data.get("source"),
        command=service_data.get("command"),
    )


def parse_agent_definition(yaml_content: str) -> AgentDefinition:
    """Parse a YAML string into an AgentDefinition.

    Expects the nested format with ``agent:`` as the top-level key.

    Args:
        yaml_content: YAML text of an agent definition file.

    Returns:
        AgentDefinition populated from the YAML content.
    """
    raw: dict[str, Any] = yaml.safe_load(yaml_content) or {}
    data: dict[str, Any] = raw.get("agent") or {}
    config = data.get("component_config")
    component_config: dict[str, Any] = config if isinstance(config, dict) else {}
    return AgentDefinition(
        ref=data.get("ref"),
        uuid=data.get("uuid"),
        version=str(data["version"]) if data.get("version") is not None else None,
        description=data.get("description"),
        orchestrator=data.get("orchestrator"),
        context_manager=data.get("context_manager"),
        provider=data.get("provider"),
        tools=_to_bool(data.get("tools")),
        hooks=_to_bool(data.get("hooks")),
        agents=_to_bool(data.get("agents")),
        context=_to_bool(data.get("context")),
        behaviors=_to_behavior_list(data.get("behaviors")),
        service=_parse_service(data.get("service")),
        component_config=component_config,
    )


def parse_behavior_definition(yaml_content: str) -> BehaviorDefinition:
    """Parse a YAML string into a BehaviorDefinition.

    Expects the nested format with ``behavior:`` as the top-level key.

    Args:
        yaml_content: YAML text of a behavior definition file.

    Returns:
        BehaviorDefinition populated from the YAML content.
    """
    raw: dict[str, Any] = yaml.safe_load(yaml_content) or {}
    data: dict[str, Any] = raw.get("behavior") or {}
    config = data.get("config")
    component_config: dict[str, Any] = config if isinstance(config, dict) else {}
    return BehaviorDefinition(
        ref=data.get("ref"),
        uuid=data.get("uuid"),
        version=str(data["version"]) if data.get("version") is not None else None,
        description=data.get("description"),
        tools=_to_bool(data.get("tools")),
        hooks=_to_bool(data.get("hooks")),
        context=_to_bool(data.get("context")),
        behaviors=_to_behavior_list(data.get("behaviors")),
        service=_parse_service(data.get("service")),
        component_config=component_config,
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
    agent_def = parse_agent_definition(agent_path.read_text())

    # Step 3: Collect service from agent, keyed by identity for deduplication.
    services_by_key: dict[tuple[str | None, str | None, str | None], ServiceEntry] = {}
    if agent_def.service is not None:
        svc = agent_def.service
        key = (svc.stack, svc.source, svc.command)
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

        # Collect service, deduplicating by identity.
        if behavior_def.service is not None:
            svc = behavior_def.service
            key = (svc.stack, svc.source, svc.command)
            if key not in services_by_key:
                services_by_key[key] = svc

        # Recurse into nested behaviors (each entry is a {alias: ref} dict).
        for behavior_dict in behavior_def.behaviors:
            for nested_behavior in behavior_dict.values():
                await _walk_behavior(nested_behavior)

    # Walk the agent's declared behaviors (each entry is a {alias: ref} dict).
    for behavior_dict in agent_def.behaviors:
        for behavior_name in behavior_dict.values():
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
