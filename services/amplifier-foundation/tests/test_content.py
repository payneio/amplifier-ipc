"""Tests for content files — verifies all content directories are discoverable via scan_content."""

from __future__ import annotations

from amplifier_ipc_protocol.discovery import scan_content


def _files_in_dir(content_files: list[str], dir_name: str) -> list[str]:
    """Return content files that live inside *dir_name* (top-level or nested)."""
    return [f for f in content_files if f.startswith(f"{dir_name}/")]


def test_agents_content_discovered() -> None:
    """At least 10 agent .md files must be discoverable under agents/."""
    content_files = scan_content("amplifier_foundation")
    agent_files = _files_in_dir(content_files, "agents")
    assert len(agent_files) >= 10, (
        f"Expected >= 10 agent files, found {len(agent_files)}: {agent_files}"
    )


def test_behaviors_content_discovered() -> None:
    """At least 5 behavior .yaml files must be discoverable under behaviors/."""
    content_files = scan_content("amplifier_foundation")
    behavior_files = _files_in_dir(content_files, "behaviors")
    assert len(behavior_files) >= 5, (
        f"Expected >= 5 behavior files, found {len(behavior_files)}: {behavior_files}"
    )


def test_context_content_discovered() -> None:
    """At least 5 context .md files must be discoverable under context/."""
    content_files = scan_content("amplifier_foundation")
    context_files = _files_in_dir(content_files, "context")
    assert len(context_files) >= 5, (
        f"Expected >= 5 context files, found {len(context_files)}: {context_files}"
    )


def test_recipes_content_discovered() -> None:
    """At least 3 recipe .yaml files must be discoverable under recipes/."""
    content_files = scan_content("amplifier_foundation")
    recipe_files = _files_in_dir(content_files, "recipes")
    assert len(recipe_files) >= 3, (
        f"Expected >= 3 recipe files, found {len(recipe_files)}: {recipe_files}"
    )


def test_sessions_content_discovered() -> None:
    """At least 3 session .yaml files must be discoverable under sessions/."""
    content_files = scan_content("amplifier_foundation")
    session_files = _files_in_dir(content_files, "sessions")
    assert len(session_files) >= 3, (
        f"Expected >= 3 session files, found {len(session_files)}: {session_files}"
    )
