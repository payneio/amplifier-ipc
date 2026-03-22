"""Tests for content files — verifies all content directories are discoverable via scan_content."""

from __future__ import annotations

import pytest

from amplifier_ipc.protocol.discovery import scan_content


@pytest.fixture(scope="module")
def content_files() -> list[str]:
    """Scan amplifier_amplifier content once for the entire test module."""
    return scan_content("amplifier_amplifier")


def _files_in_dir(content_files: list[str], dir_name: str) -> list[str]:
    """Return content files that live inside *dir_name* (top-level or nested)."""
    return [f for f in content_files if f.startswith(f"{dir_name}/")]


def test_content_discovered(content_files: list[str]) -> None:
    """At least 1 content file must be discoverable."""
    assert len(content_files) > 0, "Expected at least one content file, got none"


def test_context_content_discovered(content_files: list[str]) -> None:
    """At least 1 context file must be discoverable under context/."""
    context_files = _files_in_dir(content_files, "context")
    assert len(context_files) >= 1, (
        f"Expected >= 1 context file, found {len(context_files)}: {context_files}"
    )


def test_ecosystem_overview_present(content_files: list[str]) -> None:
    """context/ecosystem-overview.md must be present in discovered content."""
    assert "context/ecosystem-overview.md" in content_files, (
        f"Expected 'context/ecosystem-overview.md' in content files. "
        f"Found context files: {_files_in_dir(content_files, 'context')}"
    )


def test_recipes_content_discovered(content_files: list[str]) -> None:
    """At least 1 recipe file must be discoverable under recipes/."""
    recipe_files = _files_in_dir(content_files, "recipes")
    assert len(recipe_files) >= 1, (
        f"Expected >= 1 recipe file, found {len(recipe_files)}: {recipe_files}"
    )


def test_repo_audit_recipe_present(content_files: list[str]) -> None:
    """recipes/repo-audit.yaml must be present in discovered content."""
    assert "recipes/repo-audit.yaml" in content_files, (
        f"Expected 'recipes/repo-audit.yaml' in content files. "
        f"Found recipe files: {_files_in_dir(content_files, 'recipes')}"
    )


def test_content_files_are_nonempty_strings(content_files: list[str]) -> None:
    """All discovered content paths must be non-empty strings."""
    for path in content_files:
        assert isinstance(path, str), f"Expected string path, got: {type(path)}"
        assert len(path.strip()) > 0, f"Expected non-empty path, got empty string"
