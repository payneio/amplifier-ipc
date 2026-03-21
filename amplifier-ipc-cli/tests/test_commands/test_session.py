"""Tests for commands/session.py - session management commands."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Helper: create a fake session directory
# ---------------------------------------------------------------------------


def _create_session(
    sessions_dir: Path,
    session_id: str,
    name: str = "Test Session",
    messages: list[dict] | None = None,
    age_days: int = 0,
) -> Path:
    """Create a fake session directory with transcript.jsonl and metadata.json."""
    session_dir = sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # Write metadata.json
    metadata = {
        "session_id": session_id,
        "name": name,
        "status": "completed",
    }
    (session_dir / "metadata.json").write_text(json.dumps(metadata))

    # Write transcript.jsonl
    if messages is None:
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
    transcript_lines = "\n".join(json.dumps(m) for m in messages)
    (session_dir / "transcript.jsonl").write_text(transcript_lines)

    # Set mtime AFTER all file creation (so directory mtime reflects age)
    if age_days > 0:
        old_time = time.time() - (age_days * 86400)
        os.utime(session_dir, (old_time, old_time))

    return session_dir


# ---------------------------------------------------------------------------
# test_session_list_empty
# ---------------------------------------------------------------------------


class TestSessionListEmpty:
    def test_session_list_empty(self, tmp_path: Path) -> None:
        """session list shows a message when no sessions exist."""
        from amplifier_ipc_cli.commands.session import session_group

        runner = CliRunner()
        result = runner.invoke(session_group, ["--sessions-dir", str(tmp_path), "list"])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        assert "no sessions" in result.output.lower() or result.output.strip() == ""


# ---------------------------------------------------------------------------
# test_session_list_shows_sessions
# ---------------------------------------------------------------------------


class TestSessionListShowsSessions:
    def test_session_list_shows_sessions(self, tmp_path: Path) -> None:
        """session list shows a table of sessions."""
        from amplifier_ipc_cli.commands.session import session_group

        _create_session(tmp_path, "abc123def456", name="My Test Session")

        runner = CliRunner()
        result = runner.invoke(session_group, ["--sessions-dir", str(tmp_path), "list"])

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        # Session ID truncated to 8 chars + "..." => "abc123de..."
        assert "abc123d" in result.output or "My Test Session" in result.output


# ---------------------------------------------------------------------------
# test_session_show_displays_metadata
# ---------------------------------------------------------------------------


class TestSessionShowDisplaysMetadata:
    def test_session_show_displays_metadata(self, tmp_path: Path) -> None:
        """session show displays session metadata."""
        from amplifier_ipc_cli.commands.session import session_group

        session_id = "abc123def456"
        _create_session(tmp_path, session_id, name="Test Session")

        runner = CliRunner()
        result = runner.invoke(
            session_group, ["--sessions-dir", str(tmp_path), "show", session_id]
        )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        assert session_id in result.output or "Test Session" in result.output


# ---------------------------------------------------------------------------
# test_session_show_unknown_id
# ---------------------------------------------------------------------------


class TestSessionShowUnknownId:
    def test_session_show_unknown_id(self, tmp_path: Path) -> None:
        """session show prints an error for unknown session IDs."""
        from amplifier_ipc_cli.commands.session import session_group

        runner = CliRunner()
        result = runner.invoke(
            session_group, ["--sessions-dir", str(tmp_path), "show", "nonexistent"]
        )

        assert result.exit_code != 0 or "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# test_session_delete_removes_directory
# ---------------------------------------------------------------------------


class TestSessionDeleteRemovesDirectory:
    def test_session_delete_removes_directory(self, tmp_path: Path) -> None:
        """session delete --force removes the session directory."""
        from amplifier_ipc_cli.commands.session import session_group

        session_id = "abc123def456"
        session_dir = _create_session(tmp_path, session_id)

        assert session_dir.exists()

        runner = CliRunner()
        result = runner.invoke(
            session_group,
            ["--sessions-dir", str(tmp_path), "delete", "--force", session_id],
        )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        assert not session_dir.exists()


# ---------------------------------------------------------------------------
# test_session_cleanup_removes_old
# ---------------------------------------------------------------------------


class TestSessionCleanupRemovesOld:
    def test_session_cleanup_removes_old(self, tmp_path: Path) -> None:
        """session cleanup removes session directories older than --days."""
        from amplifier_ipc_cli.commands.session import session_group

        old_session = _create_session(tmp_path, "old-session-001", age_days=60)
        new_session = _create_session(tmp_path, "new-session-001", age_days=0)

        runner = CliRunner()
        result = runner.invoke(
            session_group,
            ["--sessions-dir", str(tmp_path), "cleanup", "--days", "30", "--force"],
        )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )
        assert not old_session.exists(), "Old session should have been deleted"
        assert new_session.exists(), "New session should NOT have been deleted"
