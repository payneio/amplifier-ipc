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
        from amplifier_ipc.cli.commands.session import session_group

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
        from amplifier_ipc.cli.commands.session import session_group

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
        from amplifier_ipc.cli.commands.session import session_group

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
        from amplifier_ipc.cli.commands.session import session_group

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
        from amplifier_ipc.cli.commands.session import session_group

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
        from amplifier_ipc.cli.commands.session import session_group

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


# ---------------------------------------------------------------------------
# test_session_fork_creates_new_session
# ---------------------------------------------------------------------------


class TestSessionForkCreatesNewSession:
    def test_session_fork_creates_new_session(self, tmp_path: Path) -> None:
        """session fork creates a new session directory with forked transcript."""
        from amplifier_ipc.cli.commands.session import session_group

        session_id = "abc123def456"
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I'm doing well"},
        ]
        _create_session(
            tmp_path, session_id, name="Original Session", messages=messages
        )

        runner = CliRunner()
        result = runner.invoke(
            session_group, ["--sessions-dir", str(tmp_path), "fork", session_id]
        )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )

        # Two session directories should exist now
        session_dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
        assert len(session_dirs) == 2, (
            f"Expected 2 session dirs, got {len(session_dirs)}: "
            f"{[d.name for d in session_dirs]}"
        )

        # One dir should start with "fork_"
        fork_dirs = [d for d in session_dirs if d.name.startswith("fork_")]
        assert len(fork_dirs) == 1, "Expected exactly one fork_ directory"

        # Fork should have all 4 messages
        fork_dir = fork_dirs[0]
        transcript_file = fork_dir / "transcript.jsonl"
        assert transcript_file.exists(), "Fork should have a transcript.jsonl"
        lines = [ln for ln in transcript_file.read_text().splitlines() if ln.strip()]
        assert len(lines) == 4, f"Expected 4 messages in fork, got {len(lines)}"

        # Metadata should reflect fork
        metadata_file = fork_dir / "metadata.json"
        assert metadata_file.exists()
        metadata = json.loads(metadata_file.read_text())
        assert metadata["forked_from"] == session_id
        assert "(fork)" in metadata["name"]
        assert metadata["status"] == "active"
        assert metadata["session_id"] == fork_dir.name


# ---------------------------------------------------------------------------
# test_session_fork_at_turn
# ---------------------------------------------------------------------------


class TestSessionForkAtTurn:
    def test_session_fork_at_turn(self, tmp_path: Path) -> None:
        """session fork --at-turn 1 truncates transcript to the first user turn."""
        from amplifier_ipc.cli.commands.session import session_group

        session_id = "abc123def456"
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I'm doing well"},
        ]
        _create_session(
            tmp_path, session_id, name="Original Session", messages=messages
        )

        runner = CliRunner()
        result = runner.invoke(
            session_group,
            ["--sessions-dir", str(tmp_path), "fork", "--at-turn", "1", session_id],
        )

        assert result.exit_code == 0, (
            f"Exit code: {result.exit_code}\nOutput: {result.output}\n"
            f"Exception: {result.exception}"
        )

        # Find the fork directory
        fork_dirs = [
            d for d in tmp_path.iterdir() if d.is_dir() and d.name.startswith("fork_")
        ]
        assert len(fork_dirs) == 1, "Expected exactly one fork_ directory"

        fork_dir = fork_dirs[0]
        transcript_file = fork_dir / "transcript.jsonl"
        lines = [ln for ln in transcript_file.read_text().splitlines() if ln.strip()]
        assert len(lines) == 2, (
            f"Expected 2 messages when forking at turn 1, got {len(lines)}"
        )

        # Metadata should record forked_at_turn
        metadata = json.loads((fork_dir / "metadata.json").read_text())
        assert metadata.get("forked_at_turn") == 1


# ---------------------------------------------------------------------------
# test_session_fork_at_turn_duplicate_content
# ---------------------------------------------------------------------------


class TestSessionForkAtTurnDuplicateContent:
    def test_fork_at_turn_selects_correct_assistant_when_user_messages_are_identical(
        self, tmp_path: Path
    ) -> None:
        """Fork --at-turn 2 includes the second assistant reply, not the first.

        When two user messages share identical content, the truncation loop must
        use the *current* index (not messages.index which finds the first
        occurrence) so it appends the assistant response that actually follows
        the target user turn.
        """
        from amplifier_ipc.cli.commands.session import _fork_session

        session_id = "dup_content_session"
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "Hello"},  # duplicate content
            {"role": "assistant", "content": "Goodbye"},
        ]
        session_dir = tmp_path / session_id
        session_dir.mkdir()
        import json as _json

        (session_dir / "transcript.jsonl").write_text(
            "\n".join(_json.dumps(m) for m in messages)
        )
        (session_dir / "metadata.json").write_text(
            _json.dumps(
                {"session_id": session_id, "name": "Dup Test", "status": "active"}
            )
        )

        new_id, msg_count = _fork_session(tmp_path, session_id, turn=2)

        fork_dir = tmp_path / new_id
        lines = [
            ln
            for ln in (fork_dir / "transcript.jsonl").read_text().splitlines()
            if ln.strip()
        ]
        assert msg_count == 4, f"Expected 4 messages, got {msg_count}"
        assert len(lines) == 4, f"Expected 4 lines in transcript, got {len(lines)}"

        last_msg = _json.loads(lines[-1])
        assert last_msg["content"] == "Goodbye", (
            f"Expected last message to be 'Goodbye' (the second assistant reply), "
            f"got {last_msg['content']!r}. "
            "This indicates messages.index() found the first 'Hello' instead of the second."
        )


# ---------------------------------------------------------------------------
# test_session_fork_unknown_id
# ---------------------------------------------------------------------------


class TestSessionForkUnknownId:
    def test_session_fork_unknown_id(self, tmp_path: Path) -> None:
        """session fork shows an error for unknown session IDs."""
        from amplifier_ipc.cli.commands.session import session_group

        runner = CliRunner()
        result = runner.invoke(
            session_group, ["--sessions-dir", str(tmp_path), "fork", "nonexistent"]
        )

        assert result.exit_code != 0 or "not found" in result.output.lower()
