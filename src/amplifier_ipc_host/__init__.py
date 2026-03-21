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
from amplifier_ipc_host.events import (
    ApprovalRequestEvent,
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)
from amplifier_ipc_host.host import Host
from amplifier_ipc_host.lifecycle import ServiceProcess, shutdown_service, spawn_service
from amplifier_ipc_host.persistence import SessionPersistence
from amplifier_ipc_host.definition_registry import Registry
from amplifier_ipc_host.registry import CapabilityRegistry
from amplifier_ipc_host.router import Router

__all__ = [
    # Host orchestration
    "Host",
    # Events
    "HostEvent",
    "StreamTokenEvent",
    "StreamThinkingEvent",
    "StreamToolCallStartEvent",
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
    # Registry
    "CapabilityRegistry",
    # Router
    "Router",
    # Content
    "resolve_mention",
    "assemble_system_prompt",
    # Persistence
    "SessionPersistence",
]
