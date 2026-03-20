"""Tests for session persistence module."""

from __future__ import annotations

import json
from pathlib import Path

from amplifier_ipc_host.persistence import SessionPersistence


def test_creates_session_directory(tmp_path: Path) -> None:
    """Directory created on init."""
    session_id = "test-session-001"
    persistence = SessionPersistence(session_id=session_id, base_dir=tmp_path)
    # transcript_path lives inside <base_dir>/<session_id>/ — verify the parent was created
    assert persistence.transcript_path.parent.exists()
    assert persistence.transcript_path.parent.is_dir()


def test_append_message_creates_transcript(tmp_path: Path) -> None:
    """First message creates transcript.jsonl."""
    persistence = SessionPersistence(session_id="sess-abc", base_dir=tmp_path)
    message = {"role": "user", "content": "Hello"}
    persistence.append_message(message)
    assert persistence.transcript_path.exists()


def test_append_multiple_messages(tmp_path: Path) -> None:
    """3 messages produce 3 JSONL lines."""
    persistence = SessionPersistence(session_id="sess-multi", base_dir=tmp_path)
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": "Goodbye"},
    ]
    for msg in messages:
        persistence.append_message(msg)

    lines = persistence.transcript_path.read_text().splitlines()
    assert len(lines) == 3
    for i, line in enumerate(lines):
        parsed = json.loads(line)
        assert parsed == messages[i]


def test_save_metadata(tmp_path: Path) -> None:
    """Writes metadata.json with correct content."""
    persistence = SessionPersistence(session_id="sess-meta", base_dir=tmp_path)
    metadata = {"session_id": "sess-meta", "model": "claude-3", "status": "active"}
    persistence.save_metadata(metadata)

    assert persistence.metadata_path.exists()
    loaded = json.loads(persistence.metadata_path.read_text())
    assert loaded == metadata


def test_finalize(tmp_path: Path) -> None:
    """finalize() sets status=completed in metadata."""
    persistence = SessionPersistence(session_id="sess-final", base_dir=tmp_path)
    initial_metadata = {"session_id": "sess-final", "model": "claude-3"}
    persistence.save_metadata(initial_metadata)

    persistence.finalize()

    loaded = json.loads(persistence.metadata_path.read_text())
    assert loaded["status"] == "completed"
    # Other fields should be preserved
    assert loaded["session_id"] == "sess-final"
    assert loaded["model"] == "claude-3"


def test_load_transcript(tmp_path: Path) -> None:
    """load_transcript returns all appended messages."""
    persistence = SessionPersistence(session_id="sess-load", base_dir=tmp_path)
    messages = [
        {"role": "user", "content": "First"},
        {"role": "assistant", "content": "Second"},
    ]
    for msg in messages:
        persistence.append_message(msg)

    result = persistence.load_transcript()
    assert result == messages


def test_load_transcript_empty(tmp_path: Path) -> None:
    """Returns empty list when no messages (transcript doesn't exist)."""
    persistence = SessionPersistence(session_id="sess-empty", base_dir=tmp_path)
    # Don't append anything
    result = persistence.load_transcript()
    assert result == []
