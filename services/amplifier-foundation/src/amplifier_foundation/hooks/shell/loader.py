"""Configuration loader for Claude Code hooks.

Discovers and loads hook configurations from .amplifier/hooks/ directory.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class HookConfigLoader:
    """Load and merge Claude Code hook configurations."""

    def __init__(self, hooks_dir: Path):
        self.hooks_dir = hooks_dir

    def load_all_configs(self) -> dict[str, Any]:
        """Load and merge all hook configurations."""
        configs = []

        root_config = self.hooks_dir / "hooks.json"
        if root_config.exists():
            configs.append(self._load_json(root_config))

        for subdir in self.hooks_dir.iterdir():
            if subdir.is_dir():
                config_file = subdir / "hooks.json"
                if config_file.exists():
                    configs.append(self._load_json(config_file))

        return self._merge_configs(configs)

    def _load_json(self, path: Path) -> dict[str, Any]:
        """Load a single JSON configuration file."""
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to load hook config %s: %s", path, e)
            return {}

    def _merge_configs(self, configs: list[dict[str, Any]]) -> dict[str, Any]:
        """Merge multiple hook configurations."""
        merged: dict[str, Any] = {"hooks": {}}

        for config in configs:
            for event_name, matchers in config.get("hooks", {}).items():
                if event_name not in merged["hooks"]:
                    merged["hooks"][event_name] = []

                if isinstance(matchers, list):
                    merged["hooks"][event_name].extend(matchers)
                else:
                    merged["hooks"][event_name].append(matchers)

        return merged
