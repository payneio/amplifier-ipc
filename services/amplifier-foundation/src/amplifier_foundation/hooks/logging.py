"""Logging hook — writes all session events to JSONL files."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amplifier_ipc_protocol import hook
from amplifier_ipc_protocol.models import HookAction, HookResult

logger = logging.getLogger(__name__)

SCHEMA = {"name": "amplifier.log", "ver": "1.0.0"}

# Events subscribed to by this hook
_LOG_EVENTS = [
    "session:start",
    "session:end",
    "prompt:submit",
    "prompt:complete",
    "provider:request",
    "provider:response",
    "provider:error",
    "tool:pre",
    "tool:post",
    "tool:error",
]


def _ts() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _get_project_slug(working_dir: Path | None = None) -> str:
    """Generate project slug from working directory."""
    cwd = (working_dir or Path.cwd()).resolve()
    slug = str(cwd).replace("/", "-").replace("\\", "-").replace(":", "")
    if not slug.startswith("-"):
        slug = "-" + slug
    return slug


def _sanitize_for_json(value: Any) -> Any:
    """Recursively sanitize a value to ensure JSON serializability."""
    # Fast path for primitives
    if value is None or isinstance(value, bool | int | float | str):
        return value

    # Fast path for collections - test if already JSON-safe
    if isinstance(value, (dict, list, tuple)):
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            if isinstance(value, dict):
                return {k: _sanitize_for_json(v) for k, v in value.items()}
            return [_sanitize_for_json(item) for item in value]

    # Pydantic models
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass

    # Objects with __dict__
    if hasattr(value, "__dict__"):
        try:
            return _sanitize_for_json(value.__dict__)
        except Exception:
            return str(value)

    try:
        return str(value)
    except Exception:
        return "<unserializable>"


def _write_log(
    template: str, rec: dict[str, Any], working_dir: Path | None = None
) -> None:
    """Write a log record to the session log file."""
    session_id = rec.get("session_id")
    if not session_id:
        return

    try:
        project_slug = _get_project_slug(working_dir)
        log_path = Path(
            template.format(project=project_slug, session_id=session_id)
        ).expanduser()

        log_path.parent.mkdir(parents=True, exist_ok=True)

        sanitized = _sanitize_for_json(rec)

        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sanitized, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error("Failed to write session log: %s", e)


@hook(events=_LOG_EVENTS, priority=100)
class LoggingHook:
    """Writes all session events to per-session JSONL log files.

    Removes session dependency — uses configurable log path template.
    """

    name = "logging"
    events = _LOG_EVENTS
    priority = 100

    def __init__(self) -> None:
        # Log file path template; {project} and {session_id} are expanded
        self.log_template = "~/.amplifier/logs/{project}/{session_id}/events.jsonl"
        self.working_dir: Path | None = None
        self.enabled = True

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Write event data to the session log file."""
        if not self.enabled:
            return HookResult(action=HookAction.CONTINUE)

        rec = {
            "schema": SCHEMA,
            "ts": _ts(),
            "event": event,
            **data,
        }
        _write_log(self.log_template, rec, self.working_dir)
        return HookResult(action=HookAction.CONTINUE)
