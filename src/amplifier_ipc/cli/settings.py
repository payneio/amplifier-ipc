"""Multi-scope YAML settings management.

Settings are loaded from three scopes and deep-merged (global < project < local):
  - global:  ~/.amplifier/settings.yaml
  - project: .amplifier/settings.yaml        (current working directory)
  - local:   .amplifier/settings.local.yaml  (current working directory)
"""

from __future__ import annotations

import logging
from pydantic import BaseModel
from pathlib import Path
from typing import Any, Literal

import yaml

logger = logging.getLogger(__name__)

Scope = Literal["local", "project", "global"]

_AMPLIFIER_DIR = ".amplifier"
_SETTINGS_FILENAME = "settings.yaml"
_LOCAL_SETTINGS_FILENAME = "settings.local.yaml"
_SCOPES: tuple[Scope, ...] = ("global", "project", "local")


# ---------------------------------------------------------------------------
# SettingsPaths model
# ---------------------------------------------------------------------------


class SettingsPaths(BaseModel):
    """Holds file paths for all three settings scopes."""

    global_path: Path
    project_path: Path
    local_path: Path

    @classmethod
    def default(cls) -> SettingsPaths:
        """Return default paths for all three scopes based on current environment."""
        home = Path.home()
        cwd = Path.cwd()
        return cls(
            global_path=home / _AMPLIFIER_DIR / _SETTINGS_FILENAME,
            project_path=cwd / _AMPLIFIER_DIR / _SETTINGS_FILENAME,
            local_path=cwd / _AMPLIFIER_DIR / _LOCAL_SETTINGS_FILENAME,
        )


# ---------------------------------------------------------------------------
# AppSettings
# ---------------------------------------------------------------------------


class AppSettings:
    """Manages multi-scope YAML settings with deep-merge resolution."""

    def __init__(self, paths: SettingsPaths) -> None:
        self._paths = paths

    # ------------------------------------------------------------------
    # Public merge API
    # ------------------------------------------------------------------

    def get_merged_settings(self) -> dict[str, Any]:
        """Load and deep-merge all scopes (global < project < local)."""
        result: dict[str, Any] = {}
        result = self._deep_merge(result, self._read_scope("global"))
        result = self._deep_merge(result, self._read_scope("project"))
        result = self._deep_merge(result, self._read_scope("local"))
        return result

    # ------------------------------------------------------------------
    # Core helpers
    # ------------------------------------------------------------------

    def _deep_merge(
        self, base: dict[str, Any], overlay: dict[str, Any]
    ) -> dict[str, Any]:
        """Recursively merge *overlay* into *base*; overlay wins on conflicts."""
        result = dict(base)
        for key, value in overlay.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _get_path_for_scope(self, scope: Scope) -> Path:
        """Return the file path for *scope*."""
        if scope == "global":
            return self._paths.global_path
        if scope == "project":
            return self._paths.project_path
        if scope == "local":
            return self._paths.local_path
        raise ValueError(f"Unknown scope: {scope!r}")  # pragma: no cover

    def _read_scope(self, scope: Scope) -> dict[str, Any]:
        """Read YAML settings for *scope*; returns {} if missing or malformed."""
        path = self._get_path_for_scope(scope)
        try:
            text = path.read_text()
        except FileNotFoundError:
            return {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not read %s: %s", path, exc)
            return {}
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            logger.debug("Malformed YAML in %s: %s", path, exc)
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _write_scope(self, scope: Scope, settings: dict[str, Any]) -> None:
        """Write *settings* as YAML to the file for *scope*, creating dirs as needed."""
        path = self._get_path_for_scope(scope)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(settings, default_flow_style=False))

    def _update_setting(self, key: str, value: Any, scope: Scope = "local") -> None:
        """Atomically set *key* = *value* in the given *scope* file."""
        data = self._read_scope(scope)
        data[key] = value
        self._write_scope(scope, data)

    def _remove_setting(self, key: str, scope: Scope = "local") -> None:
        """Atomically remove *key* from the given *scope* file (no-op if absent)."""
        data = self._read_scope(scope)
        data.pop(key, None)
        self._write_scope(scope, data)

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    def get_default_session(self) -> str | None:
        """Return the default session ID from the merged settings."""
        return self.get_merged_settings().get("default_session")

    def set_default_session(self, session_id: str, scope: Scope = "local") -> None:
        """Persist the default session ID to *scope*."""
        self._update_setting("default_session", session_id, scope)

    def get_provider(self) -> str | None:
        """Return the configured provider from the merged settings."""
        return self.get_merged_settings().get("provider")

    def set_provider(self, provider: str, scope: Scope = "local") -> None:
        """Persist *provider* to *scope*."""
        self._update_setting("provider", provider, scope)

    def clear_provider(self, scope: Scope = "local") -> None:
        """Remove the provider setting from *scope*."""
        self._remove_setting("provider", scope)

    def get_notification_config(self) -> dict[str, Any]:
        """Return the notification configuration from the merged settings."""
        notifications = self.get_merged_settings().get("notifications", {})
        if not isinstance(notifications, dict):
            return {}
        return notifications

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def get_routing_config(self) -> dict[str, Any]:
        """Return the routing configuration from the merged settings."""
        routing = self.get_merged_settings().get("routing", {})
        if not isinstance(routing, dict):
            return {}
        return routing

    def set_routing_matrix(self, name: str, scope: Scope = "local") -> None:
        """Persist the active routing matrix name to *scope*.

        Only the ``active_matrix`` key is modified; other settings nested
        under ``routing`` (e.g. custom weights) are preserved.
        """
        data = self._read_scope(scope)
        routing = data.get("routing", {})
        if not isinstance(routing, dict):
            routing = {}
        routing["active_matrix"] = name
        data["routing"] = routing
        self._write_scope(scope, data)

    # ------------------------------------------------------------------
    # Path lists
    # ------------------------------------------------------------------

    def _get_path_list(self, key: str) -> list[tuple[str, str]]:
        """Return a list of (path, scope) tuples for a path-list setting."""
        result: list[tuple[str, str]] = []
        for scope in _SCOPES:
            data = self._read_scope(scope)
            paths = data.get(key, [])
            if isinstance(paths, list):
                for path in paths:
                    result.append((path, scope))
        return result

    def _add_to_path_list(self, key: str, path: str, scope: Scope = "global") -> None:
        """Add *path* to the list at *key* in *scope*.

        Idempotent: no-op if path already present.
        """
        data = self._read_scope(scope)
        paths = data.get(key, [])
        if not isinstance(paths, list):
            paths = []
        if path not in paths:
            paths.append(path)
        data[key] = paths
        self._write_scope(scope, data)

    def _remove_from_path_list(
        self, key: str, path: str, scope: Scope = "global"
    ) -> bool:
        """Remove *path* from the list at *key* in *scope*. Returns True if removed."""
        data = self._read_scope(scope)
        paths = data.get(key, [])
        if not isinstance(paths, list) or path not in paths:
            return False
        paths.remove(path)
        data[key] = paths
        self._write_scope(scope, data)
        return True

    def get_allowed_write_paths(self) -> list[tuple[str, str]]:
        """Return allowed write paths as (path, scope) tuples."""
        return self._get_path_list("allowed_write_paths")

    def add_allowed_write_path(self, path: str, scope: Scope = "global") -> None:
        """Add *path* to allowed write paths at *scope*."""
        self._add_to_path_list("allowed_write_paths", path, scope)

    def remove_allowed_write_path(self, path: str, scope: Scope = "global") -> bool:
        """Remove *path* from allowed write paths at *scope*."""
        return self._remove_from_path_list("allowed_write_paths", path, scope)

    def get_denied_write_paths(self) -> list[tuple[str, str]]:
        """Return denied write paths as (path, scope) tuples."""
        return self._get_path_list("denied_write_paths")

    def add_denied_write_path(self, path: str, scope: Scope = "global") -> None:
        """Add *path* to denied write paths at *scope*."""
        self._add_to_path_list("denied_write_paths", path, scope)

    def remove_denied_write_path(self, path: str, scope: Scope = "global") -> bool:
        """Remove *path* from denied write paths at *scope*."""
        return self._remove_from_path_list("denied_write_paths", path, scope)

    # ------------------------------------------------------------------
    # Notification config (write/clear)
    # ------------------------------------------------------------------

    def set_notification_config(
        self,
        notification_type: str,
        config: dict[str, Any],
        scope: Scope = "global",
    ) -> None:
        """Persist notification config for *notification_type* at *scope*."""
        data = self._read_scope(scope)
        notifications = data.get("notifications", {})
        if not isinstance(notifications, dict):
            notifications = {}
        notifications[notification_type] = config
        data["notifications"] = notifications
        self._write_scope(scope, data)

    def clear_notification_config(
        self,
        notification_type: str | None,
        scope: Scope = "global",
    ) -> None:
        """Remove notification config for *notification_type* (or all if None)."""
        data = self._read_scope(scope)
        if notification_type is None:
            data.pop("notifications", None)
        else:
            notifications = data.get("notifications", {})
            if isinstance(notifications, dict):
                notifications.pop(notification_type, None)
                if not notifications:
                    data.pop("notifications", None)
                else:
                    data["notifications"] = notifications
        self._write_scope(scope, data)

    # ------------------------------------------------------------------
    # Provider overrides
    # ------------------------------------------------------------------

    def get_provider_overrides(self) -> list[dict[str, Any]]:
        """Return the list of provider override dicts from merged settings."""
        overrides = self.get_merged_settings().get("provider_overrides", [])
        if not isinstance(overrides, list):
            return []
        return overrides

    def set_provider_override(
        self, entry: dict[str, Any], scope: Scope = "local"
    ) -> None:
        """Add or replace a provider override entry at *scope*.

        If *entry* contains a ``"provider"`` key, any existing entry with the
        same key is replaced in-place.  If no ``"provider"`` key is present,
        *entry* is appended unconditionally.
        """
        data = self._read_scope(scope)
        overrides: list[dict[str, Any]] = data.get("provider_overrides", [])
        if not isinstance(overrides, list):
            overrides = []
        provider_key = entry.get("provider")
        if provider_key is not None:
            for i, existing in enumerate(overrides):
                if existing.get("provider") == provider_key:
                    overrides[i] = entry
                    break
            else:
                overrides.append(entry)
        else:
            overrides.append(entry)
        data["provider_overrides"] = overrides
        self._write_scope(scope, data)

    def clear_provider_override(self, scope: Scope = "local") -> bool:
        """Remove all provider overrides at *scope*.

        Returns True if any were removed.
        """
        data = self._read_scope(scope)
        overrides = data.get("provider_overrides", [])
        if not isinstance(overrides, list) or not overrides:
            return False
        data.pop("provider_overrides")
        self._write_scope(scope, data)
        return True


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_settings() -> AppSettings:
    """Return an AppSettings instance using the default path locations."""
    return AppSettings(SettingsPaths.default())
