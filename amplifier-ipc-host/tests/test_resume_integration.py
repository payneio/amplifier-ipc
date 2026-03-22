"""Integration tests for session resume via SessionPersistence."""

from __future__ import annotations

from pathlib import Path

from amplifier_ipc_host.persistence import SessionPersistence


def test_persistence_roundtrip_for_resume(tmp_path: Path) -> None:
    """Full roundtrip: write session, finalize, reload and verify all data intact."""
    session_id = "session-roundtrip"
    persistence = SessionPersistence(session_id=session_id, base_dir=tmp_path)

    # Write 4 messages (2 user/assistant pairs)
    messages = [
        {"role": "user", "content": "Hello, can you help me?"},
        {"role": "assistant", "content": "Of course! What do you need?"},
        {"role": "user", "content": "What is 2 + 2?"},
        {"role": "assistant", "content": "2 + 2 equals 4."},
    ]
    for msg in messages:
        persistence.append_message(msg)

    # Save metadata and state
    persistence.save_metadata(
        {"session_id": session_id, "model": "claude-3", "status": "active"}
    )
    persistence.save_state({"counter": 42})

    # Finalize the session
    persistence.finalize()

    # --- Load back in a new instance (simulating resume) ---
    loaded = SessionPersistence(session_id=session_id, base_dir=tmp_path)

    transcript = loaded.load_transcript()
    assert len(transcript) == 4
    assert transcript[0] == {"role": "user", "content": "Hello, can you help me?"}
    assert transcript[1] == {
        "role": "assistant",
        "content": "Of course! What do you need?",
    }
    assert transcript[2] == {"role": "user", "content": "What is 2 + 2?"}
    assert transcript[3] == {"role": "assistant", "content": "2 + 2 equals 4."}

    state = loaded.load_state()
    assert state["counter"] == 42


def test_resume_session_loads_from_previous_dir(tmp_path: Path) -> None:
    """Session written and finalized can be resumed from the same directory."""
    session_id = "session-001"

    # --- First session: write and finalize ---
    first = SessionPersistence(session_id=session_id, base_dir=tmp_path)
    first.append_message({"role": "user", "content": "Start the conversation"})
    first.append_message({"role": "assistant", "content": "Conversation started"})
    first.save_state({"turn": 1})
    first.finalize()

    # --- Second session: resume from the same base_dir and session_id ---
    second = SessionPersistence(session_id=session_id, base_dir=tmp_path)

    transcript = second.load_transcript()
    assert len(transcript) == 2
    assert transcript[0] == {"role": "user", "content": "Start the conversation"}
    assert transcript[1] == {"role": "assistant", "content": "Conversation started"}

    state = second.load_state()
    assert state["turn"] == 1
