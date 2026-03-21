"""Dataclasses and parsing functions for agent/behavior definitions."""

from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class ServiceEntry:
    """Represents a service dependency required by an agent or behavior."""

    name: str
    installer: str | None = None
    source: str | None = None


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


def _parse_services(services_data: Any) -> list[ServiceEntry]:
    """Parse a list of service dictionaries into ServiceEntry objects.

    Args:
        services_data: Raw YAML data for the services list (list of dicts or None).

    Returns:
        List of ServiceEntry instances. Empty list if services_data is None/empty.

    Raises:
        KeyError: If a service dict is missing the required 'name' key.
    """
    if not services_data:
        return []
    result = []
    for item in services_data:
        if isinstance(item, dict):
            result.append(
                ServiceEntry(
                    name=item["name"],
                    installer=item.get("installer"),
                    source=item.get("source"),
                )
            )
    return result


def parse_agent_definition(yaml_content: str) -> AgentDefinition:
    """Parse a YAML string into an AgentDefinition.

    Args:
        yaml_content: YAML text of an agent definition file.

    Returns:
        AgentDefinition populated from the YAML content.
    """
    data: dict[str, Any] = yaml.safe_load(yaml_content) or {}
    return AgentDefinition(
        type=data.get("type", "agent"),
        local_ref=data.get("local_ref"),
        uuid=data.get("uuid"),
        version=str(data["version"]) if data.get("version") is not None else None,
        description=data.get("description"),
        orchestrator=data.get("orchestrator"),
        context_manager=data.get("context_manager"),
        provider=data.get("provider"),
        behaviors=list(data.get("behaviors") or []),
        services=_parse_services(data.get("services")),
        tools=list(data.get("tools") or []),
        hooks=list(data.get("hooks") or []),
        context=dict(data.get("context") or {}),
        agents=list(data.get("agents") or []),
        component_config=dict(data.get("component_config") or {}),
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
        behaviors=list(data.get("behaviors") or []),
        services=_parse_services(data.get("services")),
        tools=list(data.get("tools") or []),
        hooks=list(data.get("hooks") or []),
        context=dict(data.get("context") or {}),
    )
