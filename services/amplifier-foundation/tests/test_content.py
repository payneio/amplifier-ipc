"""Tests for content files — verifies all content directories are discoverable via scan_content."""

from __future__ import annotations

import pytest

from amplifier_ipc.protocol.discovery import scan_content


@pytest.fixture(scope="module")
def content_files() -> list[str]:
    """Scan amplifier_foundation content once for the entire test module."""
    return scan_content("amplifier_foundation")


def _files_in_dir(content_files: list[str], dir_name: str) -> list[str]:
    """Return content files that live inside *dir_name* (top-level or nested)."""
    return [f for f in content_files if f.startswith(f"{dir_name}/")]


def test_behaviors_content_discovered(content_files: list[str]) -> None:
    """At least 5 behavior .yaml files must be discoverable under behaviors/."""
    behavior_files = _files_in_dir(content_files, "behaviors")
    assert len(behavior_files) >= 5, (
        f"Expected >= 5 behavior files, found {len(behavior_files)}: {behavior_files}"
    )


def test_context_content_discovered(content_files: list[str]) -> None:
    """At least 5 context .md files must be discoverable under context/."""
    context_files = _files_in_dir(content_files, "context")
    assert len(context_files) >= 5, (
        f"Expected >= 5 context files, found {len(context_files)}: {context_files}"
    )


def test_recipes_content_discovered(content_files: list[str]) -> None:
    """At least 3 recipe .yaml files must be discoverable under recipes/."""
    recipe_files = _files_in_dir(content_files, "recipes")
    assert len(recipe_files) >= 3, (
        f"Expected >= 3 recipe files, found {len(recipe_files)}: {recipe_files}"
    )


# NOTE: agent definitions (formerly "sessions") are referenced via fsspec URIs
# and live at the service root (services/amplifier-foundation/agents/), NOT inside
# the Python package. No sessions/ or agents/ content assertion needed here.
