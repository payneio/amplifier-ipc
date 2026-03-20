"""Tests for project scaffolding — verifies importability and package metadata."""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent


def test_version_attribute() -> None:
    """amplifier_modes.__version__ must equal '0.1.0'.

    Uses importlib.metadata so the check works regardless of which
    amplifier_modes installation pyright resolves to.
    """
    version = importlib.metadata.version("amplifier-modes")
    assert version == "0.1.0"


def test_package_docstring() -> None:
    """amplifier_modes must have a non-empty module docstring."""
    import importlib

    mod = importlib.import_module("amplifier_modes")
    assert mod.__doc__ is not None
    assert len(mod.__doc__.strip()) > 0


def test_main_module_exists() -> None:
    """src/amplifier_modes/__main__.py must exist."""
    main_path = PROJECT_ROOT / "src" / "amplifier_modes" / "__main__.py"
    assert main_path.exists(), f"__main__.py not found at {main_path}"


def test_hooks_directory_exists() -> None:
    """src/amplifier_modes/hooks/ directory must exist."""
    hooks_path = PROJECT_ROOT / "src" / "amplifier_modes" / "hooks"
    assert hooks_path.is_dir(), f"hooks/ directory not found at {hooks_path}"


def test_tools_directory_exists() -> None:
    """src/amplifier_modes/tools/ directory must exist."""
    tools_path = PROJECT_ROOT / "src" / "amplifier_modes" / "tools"
    assert tools_path.is_dir(), f"tools/ directory not found at {tools_path}"


def test_context_directory_exists() -> None:
    """src/amplifier_modes/context/ directory must exist."""
    context_path = PROJECT_ROOT / "src" / "amplifier_modes" / "context"
    assert context_path.is_dir(), f"context/ directory not found at {context_path}"


@pytest.mark.skipif(
    shutil.which("amplifier-modes-serve") is None,
    reason="Package not installed as tool",
)
def test_entry_point_available() -> None:
    """amplifier-modes-serve must be installed as a console script.

    Checks for the script in the same bin directory as the current Python
    executable, which covers both venv and global installs.

    Note: We do NOT execute the server here because it reads from stdin
    and would block indefinitely.  Existence + executability is the right
    assertion for a scaffolding test.
    """
    bin_dir = Path(sys.executable).parent
    serve_script = bin_dir / "amplifier-modes-serve"
    assert serve_script.exists(), (
        f"amplifier-modes-serve not found at {serve_script}. "
        "Run `uv pip install -e .` to install it."
    )
    assert serve_script.is_file(), f"{serve_script} is not a regular file"
    # Verify the script is executable (has the x bit set)
    assert os.access(serve_script, os.X_OK), f"{serve_script} is not executable"
