"""Tests for content files — verifies all content directories are discoverable via scan_content."""

from __future__ import annotations

import pytest

from amplifier_ipc_protocol.discovery import scan_content


@pytest.fixture(scope="module")
def content_files() -> list[str]:
    """Scan amplifier_modes content once for the entire test module."""
    return scan_content("amplifier_modes")


def _files_in_dir(content_files: list[str], dir_name: str) -> list[str]:
    """Return content files that live inside *dir_name* (top-level or nested)."""
    return [f for f in content_files if f.startswith(f"{dir_name}/")]


def test_behaviors_content_discovered(content_files: list[str]) -> None:
    """At least 1 behavior file must be discoverable under behaviors/."""
    behavior_files = _files_in_dir(content_files, "behaviors")
    assert len(behavior_files) >= 1, (
        f"Expected >= 1 behavior file, found {len(behavior_files)}: {behavior_files}"
    )


def test_behaviors_modes_yaml_present(content_files: list[str]) -> None:
    """behaviors/modes.yaml must be present in discovered content."""
    assert "behaviors/modes.yaml" in content_files, (
        f"Expected 'behaviors/modes.yaml' in content files. "
        f"Found behavior files: {_files_in_dir(content_files, 'behaviors')}"
    )


def test_context_content_discovered(content_files: list[str]) -> None:
    """At least 1 context file must be discoverable under context/."""
    context_files = _files_in_dir(content_files, "context")
    assert len(context_files) >= 1, (
        f"Expected >= 1 context file, found {len(context_files)}: {context_files}"
    )


def test_context_modes_instructions_present(content_files: list[str]) -> None:
    """context/modes-instructions.md must be present in discovered content."""
    assert "context/modes-instructions.md" in content_files, (
        f"Expected 'context/modes-instructions.md' in content files. "
        f"Found context files: {_files_in_dir(content_files, 'context')}"
    )
