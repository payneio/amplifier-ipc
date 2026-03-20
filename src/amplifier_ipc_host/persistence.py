"""Session persistence — append-only JSONL transcript with metadata storage."""

from __future__ import annotations

import json
from pathlib import Path


class SessionPersistence:
    """Manages session transcript and metadata on disk.

    Creates ``<base_dir>/<session_id>/`` on construction.
    Transcript is written as append-only JSONL; metadata as pretty-printed JSON.
    """

    def __init__(self, session_id: str, base_dir: Path) -> None:
        self._session_dir = base_dir / session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_path = self._session_dir / "transcript.jsonl"
        self.metadata_path = self._session_dir / "metadata.json"

    def append_message(self, message: dict) -> None:  # type: ignore[type-arg]
        """Append *message* as a single JSONL line to the transcript."""
        with self.transcript_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(message, separators=(",", ":")) + "\n")

    def save_metadata(self, metadata: dict) -> None:  # type: ignore[type-arg]
        """Overwrite metadata.json with *metadata* (pretty-printed)."""
        with self.metadata_path.open("w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=2)

    def finalize(self) -> None:
        """Set ``status="completed"`` in metadata and save."""
        if self.metadata_path.exists():
            with self.metadata_path.open("r", encoding="utf-8") as fh:
                metadata: dict = json.load(fh)  # type: ignore[type-arg]
        else:
            metadata = {}
        metadata["status"] = "completed"
        self.save_metadata(metadata)

    def load_transcript(self) -> list[dict]:  # type: ignore[type-arg]
        """Return all messages from the transcript, or empty list if none."""
        if not self.transcript_path.exists():
            return []
        messages = []
        with self.transcript_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    messages.append(json.loads(line))
        return messages
