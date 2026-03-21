"""Data translator between Amplifier and Claude Code formats.

Handles bidirectional translation of event data and responses.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any


class DataTranslator:
    """Translate data between Amplifier and Claude Code formats."""

    def to_claude_format(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        """Translate Amplifier event data to Claude Code format."""
        timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        if event == "PreToolUse":
            return {
                "tool_name": data.get("name", ""),
                "tool_input": data.get("input", {}),
                "timestamp": timestamp,
            }

        elif event == "PostToolUse":
            return {
                "tool_name": data.get("name", ""),
                "tool_input": data.get("input", {}),
                "tool_result": data.get("result", {}),
                "timestamp": timestamp,
            }

        elif event == "UserPromptSubmit":
            return {"prompt": data.get("prompt", ""), "timestamp": timestamp}

        elif event == "SessionStart":
            return {
                "session_id": data.get("session_id", ""),
                "trigger": data.get("trigger", "startup"),
                "timestamp": timestamp,
            }

        elif event == "SessionEnd":
            return {"session_id": data.get("session_id", ""), "timestamp": timestamp}

        return {**data, "timestamp": timestamp}

    def from_claude_response(
        self, exit_code: int, stdout: str, stderr: str
    ) -> dict[str, Any]:
        """Translate Claude Code hook response to HookResult fields."""
        if exit_code == 2:
            return {
                "action": "deny",
                "reason": stderr.strip() or "Hook blocked operation",
            }

        if stdout.strip():
            try:
                response = json.loads(stdout)
                return self._parse_json_response(response)
            except json.JSONDecodeError:
                pass

        return {"action": "continue"}

    def _parse_json_response(self, response: dict[str, Any]) -> dict[str, Any]:
        """Parse Claude Code JSON decision response."""
        result: dict[str, Any] = {}

        decision = response.get("decision", "approve")

        if decision == "block":
            result["action"] = "deny"
            result["reason"] = response.get("reason", "Hook blocked operation")
            if "systemMessage" in response:
                result["user_message"] = response["systemMessage"]
            return result

        if "contextInjection" in response:
            result["action"] = "inject_context"
            result["context_injection"] = response["contextInjection"]
            if "systemMessage" in response:
                result["user_message"] = response["systemMessage"]
            return result

        if "newContent" in response:
            result["action"] = "modify"
            result["data"] = {"modified_content": response["newContent"]}
            if "systemMessage" in response:
                result["user_message"] = response["systemMessage"]
            return result

        result["action"] = "continue"
        if "systemMessage" in response:
            result["user_message"] = response["systemMessage"]

        return result
