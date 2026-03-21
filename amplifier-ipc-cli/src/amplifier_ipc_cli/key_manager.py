"""KeyManager — load and persist API keys from ~/.amplifier/keys.env."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_KEYS_ENV_FILENAME = "keys.env"
_AMPLIFIER_DIR = ".amplifier"


class KeyManager:
    """Manages API keys stored in <base_dir>/.amplifier/keys.env.

    Keys are loaded into os.environ and saved as ``KEY="value"`` lines.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir if base_dir is not None else Path.home()
        self._keys_env_path = self._base_dir / _AMPLIFIER_DIR / _KEYS_ENV_FILENAME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_keys(self) -> None:
        """Read keys.env and set env vars for keys not already present.

        Silently does nothing if the file does not exist or cannot be read.
        """
        try:
            text = self._keys_env_path.read_text()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not read %s: %s", self._keys_env_path, exc)
            return

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, _, raw_value = stripped.partition("=")
            key = key.strip()
            value = _strip_quotes(raw_value.strip())
            if key and key not in os.environ:
                os.environ[key] = value

    def has_key(self, key_name: str) -> bool:
        """Return True if *key_name* is present in os.environ."""
        return key_name in os.environ

    def save_key(self, key_name: str, key_value: str) -> None:
        """Write *key_name* to keys.env (creating the file if needed).

        Preserves any keys already in the file.
        Sets os.environ[key_name] = key_value immediately.
        On non-Windows systems, chmod the file to 0o600.
        """
        # Ensure the directory exists
        self._keys_env_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing keys (raw lines) so we can preserve them
        existing_lines: list[str] = []
        if self._keys_env_path.exists():
            try:
                existing_lines = self._keys_env_path.read_text().splitlines()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not read %s: %s", self._keys_env_path, exc)

        # Remove any existing line for this key so we don't duplicate
        updated_lines = [ln for ln in existing_lines if not _line_has_key(ln, key_name)]

        # Build the file content
        header_lines = [
            "# Amplifier API Keys",
            "# This file is auto-managed. Do not commit to version control.",
        ]
        # Only prepend headers if the file was empty / new
        if not existing_lines:
            content_lines = header_lines + [f'{key_name}="{key_value}"']
        else:
            updated_lines.append(f'{key_name}="{key_value}"')
            content_lines = updated_lines

        self._keys_env_path.write_text("\n".join(content_lines) + "\n")

        # Restrict permissions on non-Windows
        if sys.platform != "win32":
            os.chmod(self._keys_env_path, 0o600)

        # Set in the current process environment
        os.environ[key_name] = key_value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_quotes(value: str) -> str:
    """Remove surrounding single or double quotes from *value*."""
    if len(value) >= 2:
        if (value[0] == '"' and value[-1] == '"') or (
            value[0] == "'" and value[-1] == "'"
        ):
            return value[1:-1]
    return value


def _line_has_key(line: str, key_name: str) -> bool:
    """Return True if *line* is an assignment for *key_name*."""
    stripped = line.strip()
    if stripped.startswith("#") or "=" not in stripped:
        return False
    key, _, _ = stripped.partition("=")
    return key.strip() == key_name
