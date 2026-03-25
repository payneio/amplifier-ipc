"""amplifier-ipc-host: Central message bus for Amplifier IPC services."""

from amplifier_ipc.host.config import (
    HostSettings,
    ServiceOverride,
    SessionConfig,
    load_settings,
    parse_session_config,
    resolve_service_command,
)
from amplifier_ipc.host.content import assemble_system_prompt
from amplifier_ipc.host.mentions import (
    MentionResolver,
    MentionResolverChain,
    NamespaceResolver,
    ResolvedContent,
    SyncMentionResolver,
    WorkingDirResolver,
    parse_mentions,
    resolve_and_load,
)
from amplifier_ipc.host.definition_registry import Registry
from amplifier_ipc.host.definitions import (
    AgentDefinition,
    BehaviorDefinition,
    ResolvedAgent,
    ServiceEntry,
    parse_agent_definition,
    parse_behavior_definition,
    resolve_agent,
)
from amplifier_ipc.host.events import (
    ApprovalRequestEvent,
    ChildSessionEndEvent,
    ChildSessionEvent,
    ChildSessionStartEvent,
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamContentBlockEndEvent,
    StreamContentBlockStartEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
    TodoUpdateEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from amplifier_ipc.host.host import Host
from amplifier_ipc.host.lifecycle import ServiceProcess, shutdown_service, spawn_service
from amplifier_ipc.host.persistence import SessionPersistence
from amplifier_ipc.host.service_index import ServiceIndex
from amplifier_ipc.host.router import Router
from amplifier_ipc.host.spawner import (
    SpawnRequest,
    filter_hooks,
    filter_tools,
    generate_child_session_id,
    is_top_level_session,
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
    "ToolCallEvent",
    "ToolResultEvent",
    "TodoUpdateEvent",
    "ChildSessionStartEvent",
    "ChildSessionEndEvent",
    "ChildSessionEvent",
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
    "ServiceIndex",
    # Router
    "Router",
    # Content
    "assemble_system_prompt",
    # Mentions
    "MentionResolver",
    "SyncMentionResolver",
    "MentionResolverChain",
    "NamespaceResolver",
    "WorkingDirResolver",
    "ResolvedContent",
    "parse_mentions",
    "resolve_and_load",
    # Persistence
    "SessionPersistence",
    # Spawner
    "SpawnRequest",
    "filter_hooks",
    "filter_tools",
    "generate_child_session_id",
    "is_top_level_session",
    "merge_configs",
    "spawn_child_session",
]
