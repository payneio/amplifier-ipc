"""Tests for project scaffolding — verifies importability and package metadata."""

from __future__ import annotations

import importlib.metadata
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent


def test_version_attribute() -> None:
    """amplifier_foundation.__version__ must equal '0.1.0'.

    Uses importlib.metadata so the check works regardless of which
    amplifier_foundation installation pyright resolves to.
    """
    version = importlib.metadata.version("amplifier-foundation")
    assert version == "0.1.0"


def test_package_docstring() -> None:
    """amplifier_foundation must have a non-empty module docstring."""
    import amplifier_foundation

    assert amplifier_foundation.__doc__ is not None
    assert len(amplifier_foundation.__doc__.strip()) > 0


def test_main_module_exists() -> None:
    """src/amplifier_foundation/__main__.py must exist."""
    main_path = PROJECT_ROOT / "src" / "amplifier_foundation" / "__main__.py"
    assert main_path.exists(), f"__main__.py not found at {main_path}"


def test_directory_structure() -> None:
    """All required sub-directories must exist under src/amplifier_foundation/."""
    base = PROJECT_ROOT / "src" / "amplifier_foundation"
    required_dirs = [
        "orchestrators",
        "context_managers",
        "hooks/approval",
        "hooks/routing",
        "hooks/shell",
        "tools/bash",
        "tools/filesystem",
        "tools/search",
        "tools/mcp",
        "tools/recipes",
        "tools/apply_patch",
        "tools/bundle_python_dev",
        "tools/bundle_shadow",
    ]
    for rel in required_dirs:
        path = base / rel
        assert path.is_dir(), f"Required directory missing: {path}"


def test_entry_point_available() -> None:
    """amplifier-foundation-serve must be installed as a console script.

    Checks for the script in the same bin directory as the current Python
    executable, which covers both venv and global installs.

    Note: We do NOT execute the server here because it reads from stdin
    and would block indefinitely.  Existence + executability is the right
    assertion for a scaffolding test.
    """
    bin_dir = Path(sys.executable).parent
    serve_script = bin_dir / "amplifier-foundation-serve"
    assert serve_script.exists(), (
        f"amplifier-foundation-serve not found at {serve_script}. "
        "Run `uv pip install -e '.[dev]'` to install it."
    )
    assert serve_script.is_file(), f"{serve_script} is not a regular file"
    # Verify the script is executable (has the x bit set)
    assert os.access(serve_script, os.X_OK), f"{serve_script} is not executable"
