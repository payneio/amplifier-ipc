"""amplifier-ipc-host: Central message bus for Amplifier IPC services."""

from amplifier_ipc_host.config import (
    HostSettings,
    ServiceOverride,
    SessionConfig,
    load_settings,
    parse_session_config,
    resolve_service_command,
)
from amplifier_ipc_host.content import assemble_system_prompt, resolve_mention
from amplifier_ipc_host.definition_registry import Registry
from amplifier_ipc_host.definitions import (
    AgentDefinition,
    BehaviorDefinition,
    ResolvedAgent,
    ServiceEntry,
    parse_agent_definition,
    parse_behavior_definition,
    resolve_agent,
)
from amplifier_ipc_host.events import (
    ApprovalRequestEvent,
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamContentBlockEndEvent,
    StreamContentBlockStartEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)
from amplifier_ipc_host.host import Host
from amplifier_ipc_host.lifecycle import ServiceProcess, shutdown_service, spawn_service
from amplifier_ipc_host.persistence import SessionPersistence
from amplifier_ipc_host.registry import CapabilityRegistry
from amplifier_ipc_host.router import Router
from amplifier_ipc_host.spawner import (
    SpawnRequest,
    filter_hooks,
    filter_tools,
    generate_child_session_id,
    merge_configs,
    spawn_child_session,
)

__all__ = [
    # Host orchestration
    "Host",
    # Events
    "HostEvent",
    "StreamTokenEvent",
    "StreamThinkingEvent",
    "StreamToolCallStartEvent",
    "StreamContentBlockStartEvent",
    "StreamContentBlockEndEvent",
    "ApprovalRequestEvent",
    "ErrorEvent",
    "CompleteEvent",
    # Config
    "SessionConfig",
    "HostSettings",
    "ServiceOverride",
    "parse_session_config",
    "load_settings",
    "resolve_service_command",
    # Lifecycle
    "ServiceProcess",
    "spawn_service",
    "shutdown_service",
    # Definition registry
    "Registry",
    # Definitions
    "AgentDefinition",
    "BehaviorDefinition",
    "ResolvedAgent",
    "ServiceEntry",
    "parse_agent_definition",
    "parse_behavior_definition",
    "resolve_agent",
    # Registry
    "CapabilityRegistry",
    # Router
    "Router",
    # Content
    "resolve_mention",
    "assemble_system_prompt",
    # Persistence
    "SessionPersistence",
    # Spawner
    "SpawnRequest",
    "filter_hooks",
    "filter_tools",
    "generate_child_session_id",
    "merge_configs",
    "spawn_child_session",
]
