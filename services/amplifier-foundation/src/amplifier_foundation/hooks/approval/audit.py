"""Audit trail logging for approval decisions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default audit file location
DEFAULT_AUDIT_FILE = Path.home() / ".amplifier" / "audit" / "approvals.jsonl"


@dataclass
class ApprovalRequest:
    """Approval request details."""

    tool_name: str
    action: str
    details: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "medium"
    timeout: float | None = None


@dataclass
class ApprovalResponse:
    """Approval response."""

    approved: bool
    reason: str | None = None
    remember: bool = False


def audit_log(
    request: ApprovalRequest,
    response: ApprovalResponse,
    audit_file: Path | None = None,
) -> None:
    """Log approval request and response to audit trail.

    Args:
        request: Approval request
        response: Approval response
        audit_file: Optional custom audit file path
    """
    if audit_file is None:
        audit_file = DEFAULT_AUDIT_FILE

    audit_file.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "timestamp": datetime.now().isoformat(),
        "request": {
            "tool_name": request.tool_name,
            "action": request.action,
            "risk_level": request.risk_level,
            "details": request.details,
            "timeout": request.timeout,
        },
        "response": {
            "approved": response.approved,
            "reason": response.reason,
            "remember": response.remember,
        },
    }

    try:
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error("Failed to write audit log: %s", e)
