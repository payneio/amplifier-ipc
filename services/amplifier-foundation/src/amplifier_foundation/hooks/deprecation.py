"""Deprecation hook — warns once per session about deprecated bundles."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from amplifier_ipc.protocol import hook
from amplifier_ipc.protocol.models import HookAction, HookResult

logger = logging.getLogger(__name__)


@dataclass
class DeprecationConfig:
    """Parsed and validated deprecation configuration."""

    bundle_name: str
    message: str
    replacement: str | None = None
    migration: str | None = None
    severity: str = "warning"  # "warning" or "info"
    sunset_date: date | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DeprecationConfig:
        """Parse and validate config from a raw dict.

        Required keys: bundle_name, message.
        Optional keys: replacement, migration, severity, sunset_date.

        Raises:
            ValueError: If required keys are missing or values are invalid.
        """
        bundle_name = raw.get("bundle_name")
        if not bundle_name:
            raise ValueError("bundle_name is required in deprecation hook config")

        message = raw.get("message")
        if not message:
            raise ValueError("message is required in deprecation hook config")

        severity = raw.get("severity", "warning")
        if severity not in ("warning", "info"):
            raise ValueError(f"severity must be 'warning' or 'info', got '{severity}'")

        sunset_date = None
        raw_date = raw.get("sunset_date")
        if raw_date:
            try:
                sunset_date = date.fromisoformat(str(raw_date))
            except ValueError:
                raise ValueError(
                    f"sunset_date must be YYYY-MM-DD format, got '{raw_date}'"
                )

        return cls(
            bundle_name=bundle_name,
            message=message,
            replacement=raw.get("replacement"),
            migration=raw.get("migration"),
            severity=severity,
            sunset_date=sunset_date,
        )


def find_source_files(bundle_name: str, search_dirs: list[Path]) -> list[str]:
    """Scan .amplifier/ directories for files referencing the deprecated bundle."""
    found: list[str] = []
    for base_dir in search_dirs:
        amp_dir = base_dir / ".amplifier"
        if not amp_dir.is_dir():
            continue
        for yaml_file in amp_dir.rglob("*.yaml"):
            try:
                content = yaml_file.read_text(encoding="utf-8")
                if bundle_name in content:
                    found.append(str(yaml_file))
            except (OSError, UnicodeDecodeError):
                continue
    return found


def effective_severity(config: DeprecationConfig) -> str:
    """Compute effective severity, escalating if sunset_date is past."""
    if config.sunset_date and config.sunset_date < date.today():
        if config.severity == "info":
            return "warning"
        if config.severity == "warning":
            return "urgent"
    return config.severity


def build_warning_text(
    config: DeprecationConfig,
    severity: str,
    source_files: list[str],
) -> str:
    """Build the AI context injection text block."""
    if severity == "urgent":
        header = f"URGENT DEPRECATION WARNING: {config.bundle_name}"
    else:
        header = f"DEPRECATION WARNING: {config.bundle_name}"

    lines = [header, "", config.message]

    if config.replacement:
        lines.append(f"Replacement: {config.replacement}")

    if config.sunset_date:
        lines.append(f"Sunset date: {config.sunset_date.isoformat()}")

    if source_files:
        lines.append("")
        lines.append("Found in:")
        for path in source_files:
            lines.append(f"  - {path}")

    if config.migration:
        lines.append("")
        lines.append("Migration steps:")
        lines.append(config.migration)

    return "\n".join(lines)


def build_user_message(config: DeprecationConfig, severity: str) -> str:
    """Build the user-visible warning message."""
    prefix = "URGENT: " if severity == "urgent" else ""
    msg = f"{prefix}Deprecated bundle '{config.bundle_name}': {config.message}"
    if config.replacement:
        msg += f" → Use '{config.replacement}' instead."
    return msg


@hook(events=["session:start"], priority=10)
class DeprecationHook:
    """Fires a deprecation warning once per session via context injection."""

    name = "deprecation"
    events = ["session:start"]
    priority = 10

    def __init__(self) -> None:
        self._fired = False
        self.config: DeprecationConfig | None = None
        self.search_dirs: list[Path] = []

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch to the appropriate handler based on event."""
        if event == "session:start":
            return await self._on_session_start(event, data)
        return HookResult(action=HookAction.CONTINUE)

    async def _on_session_start(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle session:start event. Fires once per session."""
        if self._fired:
            return HookResult(action=HookAction.CONTINUE)
        self._fired = True

        if self.config is None:
            return HookResult(action=HookAction.CONTINUE)

        severity = effective_severity(self.config)
        source_files = find_source_files(self.config.bundle_name, self.search_dirs)
        context_text = build_warning_text(self.config, severity, source_files)
        user_msg = build_user_message(self.config, severity)

        if severity in ("warning", "urgent"):
            msg_level = "warning"
        else:
            msg_level = "info"

        # No-op: emit deprecation:warning event (was hooks.emit() in old pattern)
        logger.info(
            "deprecation:warning bundle=%s replacement=%s severity=%s files=%s",
            self.config.bundle_name,
            self.config.replacement,
            severity,
            source_files,
        )

        return HookResult(
            action=HookAction.INJECT_CONTEXT,
            context_injection=context_text,
            context_injection_role="system",
            data={
                "user_message": user_msg,
                "user_message_level": msg_level,
                "user_message_source": "deprecation",
            },
        )
