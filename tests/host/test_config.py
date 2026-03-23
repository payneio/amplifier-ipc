"""Tests for config parsing module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings

from amplifier_ipc.host.config import (
    HostSettings,
    ServiceOverride,
    SessionConfig,
    load_settings,
    parse_session_config,
    resolve_service_command,
)


# ---------------------------------------------------------------------------
# Pydantic model type tests (RED until config.py is converted)
# ---------------------------------------------------------------------------


def test_service_override_is_pydantic_base_model() -> None:
    """ServiceOverride must inherit from pydantic BaseModel."""
    override = ServiceOverride()
    assert isinstance(override, BaseModel)


def test_host_settings_is_pydantic_base_settings() -> None:
    """HostSettings must inherit from pydantic_settings BaseSettings."""
    settings = HostSettings()
    assert isinstance(settings, BaseSettings)


def test_host_settings_env_prefix() -> None:
    """HostSettings model_config must have env_prefix='AMPLIFIER_IPC_'."""
    assert HostSettings.model_config["env_prefix"] == "AMPLIFIER_IPC_"


def test_host_settings_env_nested_delimiter() -> None:
    """HostSettings model_config must have env_nested_delimiter='__'."""
    assert HostSettings.model_config["env_nested_delimiter"] == "__"


def test_session_config_is_pydantic_base_model() -> None:
    """SessionConfig must inherit from pydantic BaseModel."""
    cfg = SessionConfig(
        services=["svc"],
        orchestrator="orch",
        context_manager="ctx",
        provider="anthropic",
    )
    assert isinstance(cfg, BaseModel)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, filename: str, data: object) -> Path:
    p = tmp_path / filename
    p.write_text(yaml.dump(data))
    return p


# ---------------------------------------------------------------------------
# parse_session_config
# ---------------------------------------------------------------------------


def test_parse_minimal_session_config(tmp_path: Path) -> None:
    config_file = _write_yaml(
        tmp_path,
        "session.yaml",
        {
            "session": {
                "services": ["tool-server", "context-manager"],
                "orchestrator": "orchestrator-svc",
                "context_manager": "ctx-svc",
                "provider": "anthropic",
            }
        },
    )

    cfg = parse_session_config(config_file)

    assert isinstance(cfg, SessionConfig)
    assert cfg.services == ["tool-server", "context-manager"]
    assert cfg.orchestrator == "orchestrator-svc"
    assert cfg.context_manager == "ctx-svc"
    assert cfg.provider == "anthropic"
    assert cfg.component_config == {}


def test_parse_session_config_with_component_config(tmp_path: Path) -> None:
    config_file = _write_yaml(
        tmp_path,
        "session.yaml",
        {
            "session": {
                "services": ["tool-server"],
                "orchestrator": "orch",
                "context_manager": "ctx",
                "provider": "openai",
                "config": {
                    "tool": {"timeout": 30},
                    "orchestrator": {"model": "gpt-4"},
                },
            }
        },
    )

    cfg = parse_session_config(config_file)

    assert cfg.component_config == {
        "tool": {"timeout": 30},
        "orchestrator": {"model": "gpt-4"},
    }


def test_parse_session_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        parse_session_config(tmp_path / "nonexistent.yaml")


def test_parse_session_config_missing_services(tmp_path: Path) -> None:
    config_file = _write_yaml(
        tmp_path,
        "session.yaml",
        {
            "session": {
                "orchestrator": "orch",
                "context_manager": "ctx",
                "provider": "anthropic",
            }
        },
    )

    with pytest.raises(ValueError):
        parse_session_config(config_file)


# ---------------------------------------------------------------------------
# load_settings
# ---------------------------------------------------------------------------


def test_load_settings_empty(tmp_path: Path) -> None:
    settings = load_settings(
        user_settings_path=tmp_path / "user_settings.yaml",
        project_settings_path=tmp_path / "project_settings.yaml",
    )

    assert isinstance(settings, HostSettings)
    assert settings.service_overrides == {}


def test_load_settings_user_overrides(tmp_path: Path) -> None:
    user_settings = _write_yaml(
        tmp_path,
        "user_settings.yaml",
        {
            "amplifier_ipc": {
                "service_overrides": {
                    "tool-server": {
                        "command": ["python", "-m", "tool_server"],
                        "working_dir": "/home/user/projects",
                    }
                }
            }
        },
    )

    settings = load_settings(
        user_settings_path=user_settings,
        project_settings_path=tmp_path / "project_settings.yaml",
    )

    assert "tool-server" in settings.service_overrides
    override = settings.service_overrides["tool-server"]
    assert isinstance(override, ServiceOverride)
    assert override.command == ["python", "-m", "tool_server"]
    assert override.working_dir == "/home/user/projects"


def test_load_settings_project_overrides_user(tmp_path: Path) -> None:
    user_settings = _write_yaml(
        tmp_path,
        "user_settings.yaml",
        {
            "amplifier_ipc": {
                "service_overrides": {
                    "tool-server": {
                        "command": ["user-cmd"],
                        "working_dir": "/user/dir",
                    }
                }
            }
        },
    )
    project_settings = _write_yaml(
        tmp_path,
        "project_settings.yaml",
        {
            "amplifier_ipc": {
                "service_overrides": {
                    "tool-server": {
                        "command": ["project-cmd"],
                        "working_dir": "/project/dir",
                    }
                }
            }
        },
    )

    settings = load_settings(
        user_settings_path=user_settings,
        project_settings_path=project_settings,
    )

    override = settings.service_overrides["tool-server"]
    assert override.command == ["project-cmd"]
    assert override.working_dir == "/project/dir"


# ---------------------------------------------------------------------------
# resolve_service_command
# ---------------------------------------------------------------------------


def test_resolve_service_command_no_override() -> None:
    settings = HostSettings()
    command, cwd = resolve_service_command("my-service", settings)

    assert command == ["my-service"]
    assert cwd is None


def test_resolve_service_command_with_override() -> None:
    settings = HostSettings(
        service_overrides={
            "my-service": ServiceOverride(
                command=["custom-cmd", "--flag"],
                working_dir="/custom/dir",
            )
        }
    )
    command, cwd = resolve_service_command("my-service", settings)

    assert command == ["custom-cmd", "--flag"]
    assert cwd == "/custom/dir"


def test_resolve_service_command_override_no_working_dir() -> None:
    settings = HostSettings(
        service_overrides={
            "my-service": ServiceOverride(
                command=["custom-cmd"],
            )
        }
    )
    command, cwd = resolve_service_command("my-service", settings)

    assert command == ["custom-cmd"]
    assert cwd is None


def test_load_settings_nested_agent_format(tmp_path: Path) -> None:
    """load_settings with agent_name extracts nested agent->service overrides.

    The .amplifier/settings.yaml now uses a nested structure:
      amplifier_ipc.service_overrides.<agent_name>.<service_ref>: {command, working_dir}

    When agent_name is given, load_settings must descend into that agent's section
    and return per-service overrides, not treat the agent name itself as a service.
    """
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "amplifier_ipc:\n"
        "  service_overrides:\n"
        "    my-agent:\n"
        "      foundation:\n"
        "        command: [uv, run, amplifier-foundation-serve]\n"
        "        working_dir: ./services/amplifier-foundation\n"
        "      modes:\n"
        "        command: [uv, run, amplifier-modes-serve]\n"
    )

    settings = load_settings(
        user_settings_path=tmp_path / "no-user.yaml",
        project_settings_path=settings_file,
        agent_name="my-agent",
    )

    assert "foundation" in settings.service_overrides
    assert "modes" in settings.service_overrides
    # The agent name itself must NOT appear as a service
    assert "my-agent" not in settings.service_overrides

    foundation = settings.service_overrides["foundation"]
    assert foundation.command == ["uv", "run", "amplifier-foundation-serve"]
    assert foundation.working_dir == "./services/amplifier-foundation"

    modes = settings.service_overrides["modes"]
    assert modes.command == ["uv", "run", "amplifier-modes-serve"]


def test_load_settings_nested_unknown_agent_returns_empty(tmp_path: Path) -> None:
    """load_settings with an unknown agent_name returns empty overrides (no crash)."""
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "amplifier_ipc:\n"
        "  service_overrides:\n"
        "    other-agent:\n"
        "      some-service:\n"
        "        command: [cmd]\n"
    )

    settings = load_settings(
        user_settings_path=tmp_path / "no-user.yaml",
        project_settings_path=settings_file,
        agent_name="unknown-agent",
    )

    assert settings.service_overrides == {}


def test_resolve_service_command_empty_override_falls_through() -> None:
    """ServiceOverride with empty command must not be returned.

    An override of command=[] is a misconfiguration that would cause
    asyncio.create_subprocess_exec(*[]) to raise TypeError.  The guard
    ``if override is not None and override.command`` must treat an empty
    list as "no override" and fall back to the service-name default.
    """
    settings = HostSettings(
        service_overrides={
            "my-service": ServiceOverride(command=[]),
        }
    )
    command, cwd = resolve_service_command("my-service", settings)

    # Empty command override must be ignored; fall through to default.
    assert command == ["my-service"]
    assert cwd is None
