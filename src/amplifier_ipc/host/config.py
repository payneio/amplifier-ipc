"""Config parsing for session YAML files and host settings overrides."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ServiceOverride(BaseModel):
    """Command and working directory override for a named service."""

    command: list[str] = Field(default_factory=list)
    working_dir: str | None = None


class HostSettings(BaseSettings):
    """Host-level settings loaded from user/project YAML settings files.

    Supports environment variable configuration via the ``AMPLIFIER_IPC_``
    prefix (e.g. ``AMPLIFIER_IPC_SERVICE_OVERRIDES__my_service__command``).
    """

    model_config = SettingsConfigDict(
        env_prefix="AMPLIFIER_IPC_",
        env_nested_delimiter="__",
    )

    service_overrides: dict[str, ServiceOverride] = Field(default_factory=dict)


class SessionConfig(BaseModel):
    """Parsed representation of a session YAML configuration file."""

    services: list[str]
    orchestrator: str
    context_manager: str
    provider: str
    component_config: dict[str, dict[str, Any]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------


def parse_session_config(path: Path) -> SessionConfig:
    """Read a session YAML file and return a SessionConfig.

    Args:
        path: Path to the YAML file.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the ``services`` key is missing from the ``session`` section.
    """
    if not path.exists():
        raise FileNotFoundError(f"Session config file not found: {path}")

    raw = yaml.safe_load(path.read_text())
    session = raw.get("session", {}) if raw else {}

    if "services" not in session:
        raise ValueError("Session config is missing required 'services' field")

    return SessionConfig(
        services=session["services"],
        orchestrator=session.get("orchestrator", ""),
        context_manager=session.get("context_manager", ""),
        provider=session.get("provider", ""),
        component_config=session.get("config", {}),
    )


def load_settings(
    *,
    user_settings_path: Path,
    project_settings_path: Path,
    agent_name: str | None = None,
) -> HostSettings:
    """Load and merge service override settings from user and project YAML files.

    User settings are loaded first (lower priority); project settings are
    applied on top and override any matching keys.  If a file does not exist
    it is silently skipped.

    Settings are read from the ``amplifier_ipc.service_overrides`` namespace.

    Two formats are supported:

    *Flat format* (legacy, used when ``agent_name`` is ``None``):

    .. code-block:: yaml

        amplifier_ipc:
          service_overrides:
            my-service:
              command: [uv, run, my-service]
              working_dir: ./services/my-service

    *Nested format* (new, used when ``agent_name`` is provided):

    .. code-block:: yaml

        amplifier_ipc:
          service_overrides:
            my-agent:
              my-service:
                command: [uv, run, my-service]
                working_dir: ./services/my-service

    Args:
        user_settings_path: Path to the user-level settings YAML file.
        project_settings_path: Path to the project-level settings YAML file.
        agent_name: When provided, extract service overrides from the nested
                    ``service_overrides.<agent_name>`` sub-section instead of
                    reading the top-level flat mapping.
    """
    merged: dict[str, ServiceOverride] = {}

    for settings_path in (user_settings_path, project_settings_path):
        if not settings_path.exists():
            continue

        raw = yaml.safe_load(settings_path.read_text())
        if not raw:
            continue

        service_overrides_section = (
            raw.get("amplifier_ipc", {}).get("service_overrides", {}) or {}
        )

        if agent_name is not None:
            # Nested format: descend into the agent-specific sub-section.
            overrides = service_overrides_section.get(agent_name, {}) or {}
        else:
            overrides = service_overrides_section

        for service_name, override_data in overrides.items():
            if not isinstance(override_data, dict):
                continue
            merged[service_name] = ServiceOverride(
                command=override_data.get("command", []),
                working_dir=override_data.get("working_dir"),
            )

    return HostSettings(service_overrides=merged)


def resolve_service_command(
    service_name: str,
    settings: HostSettings,
) -> tuple[list[str], str | None]:
    """Return the command and working directory for *service_name*.

    If an override is registered in *settings* the override values are
    returned.  Otherwise the service name is used as the command with no
    working directory.
    """
    override = settings.service_overrides.get(service_name)
    if override is not None and override.command:
        return override.command, override.working_dir

    return [service_name], None
