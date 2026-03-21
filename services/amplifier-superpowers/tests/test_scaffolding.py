"""Tests for project scaffolding — verifies importability and package metadata."""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent


def test_version_attribute() -> None:
    """amplifier_superpowers.__version__ must equal '0.1.0'."""
    version = importlib.metadata.version("amplifier-superpowers")
    assert version == "0.1.0"


def test_package_docstring() -> None:
    """amplifier_superpowers must have a non-empty module docstring."""
    mod = importlib.import_module("amplifier_superpowers")
    assert mod.__doc__ is not None
    assert len(mod.__doc__.strip()) > 0


def test_main_module_exists() -> None:
    """src/amplifier_superpowers/__main__.py must exist."""
    main_path = PROJECT_ROOT / "src" / "amplifier_superpowers" / "__main__.py"
    assert main_path.exists(), f"__main__.py not found at {main_path}"


def test_main_has_main_function() -> None:
    """amplifier_superpowers.__main__ must export a main() function."""
    mod = importlib.import_module("amplifier_superpowers.__main__")
    assert hasattr(mod, "main"), "__main__.py must define a main() function"
    assert callable(mod.main)


def test_behaviors_directory_exists() -> None:
    """src/amplifier_superpowers/behaviors/ directory must exist."""
    behaviors_path = PROJECT_ROOT / "src" / "amplifier_superpowers" / "behaviors"
    assert behaviors_path.is_dir(), f"behaviors/ directory not found at {behaviors_path}"


def test_context_directory_exists() -> None:
    """src/amplifier_superpowers/context/ directory must exist."""
    context_path = PROJECT_ROOT / "src" / "amplifier_superpowers" / "context"
    assert context_path.is_dir(), f"context/ directory not found at {context_path}"


def test_recipes_directory_exists() -> None:
    """src/amplifier_superpowers/recipes/ directory must exist."""
    recipes_path = PROJECT_ROOT / "src" / "amplifier_superpowers" / "recipes"
    assert recipes_path.is_dir(), f"recipes/ directory not found at {recipes_path}"


def test_entry_point_available() -> None:
    """amplifier-superpowers-serve must be installed as a console script."""
    bin_dir = Path(sys.executable).parent
    serve_script = bin_dir / "amplifier-superpowers-serve"
    if not serve_script.exists():
        pytest.skip("Package not installed as tool — run `uv pip install -e .`")
    assert serve_script.is_file(), f"{serve_script} is not a regular file"
    assert os.access(serve_script, os.X_OK), f"{serve_script} is not executable"
