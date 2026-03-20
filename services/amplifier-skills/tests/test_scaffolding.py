"""Tests for project scaffolding — verifies importability and package metadata."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent


def test_version_attribute() -> None:
    """amplifier_skills.__version__ must equal '0.1.0'.

    Reads the attribute directly from the module rather than via
    importlib.metadata so the check works whether or not the package has been
    installed as a dist (e.g. when pytest adds src/ to sys.path via pythonpath).
    """
    import amplifier_skills  # type: ignore[import-untyped]

    assert amplifier_skills.__version__ == "0.1.0"


def test_package_docstring() -> None:
    """amplifier_skills must have a non-empty module docstring."""
    import importlib

    mod = importlib.import_module("amplifier_skills")
    assert mod.__doc__ is not None
    assert len(mod.__doc__.strip()) > 0


def test_main_module_exists() -> None:
    """src/amplifier_skills/__main__.py must exist."""
    main_path = PROJECT_ROOT / "src" / "amplifier_skills" / "__main__.py"
    assert main_path.exists(), f"__main__.py not found at {main_path}"


def test_tools_directory_exists() -> None:
    """src/amplifier_skills/tools/ directory must exist."""
    tools_path = PROJECT_ROOT / "src" / "amplifier_skills" / "tools"
    assert tools_path.is_dir(), f"tools/ directory not found at {tools_path}"


def test_context_directory_exists() -> None:
    """src/amplifier_skills/context/ directory must exist."""
    context_path = PROJECT_ROOT / "src" / "amplifier_skills" / "context"
    assert context_path.is_dir(), f"context/ directory not found at {context_path}"


def test_skills_tool_importable() -> None:
    """amplifier_skills.tools.skills.tool.SkillsTool must be importable."""
    from amplifier_skills.tools.skills.tool import SkillsTool  # type: ignore[import-untyped]  # noqa: F401


def test_skills_discovery_importable() -> None:
    """amplifier_skills.tools.skills.discovery must be importable."""
    from amplifier_skills.tools.skills.discovery import (  # type: ignore[import-untyped]  # noqa: F401
        discover_skills,
        discover_skills_multi_source,
        extract_skill_body,
        get_default_skills_dirs,
    )


def test_skills_sources_importable() -> None:
    """amplifier_skills.tools.skills.sources must be importable."""
    from amplifier_skills.tools.skills.sources import (  # type: ignore[import-untyped]  # noqa: F401
        is_remote_source,
        resolve_skill_source,
    )


def test_skills_tool_proxy_importable() -> None:
    """amplifier_skills.tools.skills_tool (proxy) must be importable."""
    from amplifier_skills.tools.skills_tool import SkillsTool  # type: ignore[import-untyped]  # noqa: F401


@pytest.mark.skipif(
    shutil.which("amplifier-skills-serve") is None,
    reason="Package not installed as tool",
)
def test_entry_point_available() -> None:
    """amplifier-skills-serve must be installed as a console script.

    Checks for the script in the same bin directory as the current Python
    executable, which covers both venv and global installs.

    Note: We do NOT execute the server here because it reads from stdin
    and would block indefinitely.  Existence + executability is the right
    assertion for a scaffolding test.
    """
    bin_dir = Path(sys.executable).parent
    serve_script = bin_dir / "amplifier-skills-serve"
    assert serve_script.exists(), (
        f"amplifier-skills-serve not found at {serve_script}. "
        "Run `uv pip install -e .` to install it."
    )
    assert serve_script.is_file(), f"{serve_script} is not a regular file"
    assert os.access(serve_script, os.X_OK), f"{serve_script} is not executable"
