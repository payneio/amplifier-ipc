"""Tests for content files — verifies all content directories are discoverable
and skills instruction files are accessible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_ipc.protocol.discovery import scan_content


PROJECT_ROOT = Path(__file__).parent.parent
PACKAGE_DIR = PROJECT_ROOT / "src" / "amplifier_skills"


@pytest.fixture(scope="module")
def content_files() -> list[str]:
    """Scan amplifier_skills content once for the entire test module."""
    return scan_content("amplifier_skills")


def _files_in_dir(content_files: list[str], dir_name: str) -> list[str]:
    """Return content files that live inside *dir_name* (top-level or nested)."""
    return [f for f in content_files if f.startswith(f"{dir_name}/")]


# ---------------------------------------------------------------------------
# Context content
# ---------------------------------------------------------------------------


def test_context_content_discovered(content_files: list[str]) -> None:
    """At least 1 context file must be discoverable under context/."""
    context_files = _files_in_dir(content_files, "context")
    assert len(context_files) >= 1, (
        f"Expected >= 1 context file, found {len(context_files)}: {context_files}"
    )


def test_context_skills_instructions_present(content_files: list[str]) -> None:
    """context/skills-instructions.md must be present in discovered content."""
    assert "context/skills-instructions.md" in content_files, (
        f"Expected 'context/skills-instructions.md' in content files. "
        f"Found context files: {_files_in_dir(content_files, 'context')}"
    )


def test_context_files_are_non_empty(content_files: list[str]) -> None:
    """All discovered context files must be non-empty."""
    context_files = _files_in_dir(content_files, "context")
    for rel_path in context_files:
        abs_path = PACKAGE_DIR / rel_path
        assert abs_path.exists(), f"Context file does not exist: {abs_path}"
        content = abs_path.read_text(encoding="utf-8").strip()
        assert len(content) > 0, f"Context file is empty: {rel_path}"


# ---------------------------------------------------------------------------
# Skills tool structure
# ---------------------------------------------------------------------------


def test_skills_tool_directory_exists() -> None:
    """src/amplifier_skills/tools/skills/ directory must contain expected modules."""
    skills_dir = PACKAGE_DIR / "tools" / "skills"
    assert skills_dir.is_dir(), f"tools/skills/ not found at {skills_dir}"

    expected_files = ["tool.py", "discovery.py", "sources.py"]
    for filename in expected_files:
        file_path = skills_dir / filename
        assert file_path.exists(), (
            f"Expected {filename} in tools/skills/, not found at {file_path}"
        )


def test_skills_tool_proxy_exists() -> None:
    """src/amplifier_skills/tools/skills_tool.py (IPC proxy) must exist."""
    proxy_path = PACKAGE_DIR / "tools" / "skills_tool.py"
    assert proxy_path.exists(), f"skills_tool.py proxy not found at {proxy_path}"


def test_skills_instructions_content_is_meaningful(content_files: list[str]) -> None:
    """context/skills-instructions.md must contain meaningful content about skills."""
    assert "context/skills-instructions.md" in content_files, (
        "context/skills-instructions.md not in discovered content"
    )
    instructions_path = PACKAGE_DIR / "context" / "skills-instructions.md"
    content = instructions_path.read_text(encoding="utf-8")
    # Should reference the load_skill tool
    assert "load_skill" in content, (
        f"Expected 'load_skill' reference in skills-instructions.md"
    )
