"""Tests for config parsing module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from amplifier_ipc_host.config import (
    HostSettings,
    ServiceOverride,
    SessionConfig,
    load_settings,
    parse_session_config,
    resolve_service_command,
)


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
