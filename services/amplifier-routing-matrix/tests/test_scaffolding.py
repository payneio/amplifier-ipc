"""Tests for project scaffolding — verifies importability and package metadata."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent


def test_version_attribute() -> None:
    """amplifier_routing_matrix.__version__ must equal '0.1.0'.

    Reads the attribute directly from the module rather than via
    importlib.metadata so the check works whether or not the package has been
    installed as a dist (e.g. when pytest adds src/ to sys.path via pythonpath).
    """
    import amplifier_routing_matrix  # type: ignore[import-untyped]

    assert amplifier_routing_matrix.__version__ == "0.1.0"


def test_package_docstring() -> None:
    """amplifier_routing_matrix must have a non-empty module docstring."""
    import importlib

    mod = importlib.import_module("amplifier_routing_matrix")
    assert mod.__doc__ is not None
    assert len(mod.__doc__.strip()) > 0


def test_main_module_exists() -> None:
    """src/amplifier_routing_matrix/__main__.py must exist."""
    main_path = PROJECT_ROOT / "src" / "amplifier_routing_matrix" / "__main__.py"
    assert main_path.exists(), f"__main__.py not found at {main_path}"


def test_hooks_directory_exists() -> None:
    """src/amplifier_routing_matrix/hooks/ directory must exist."""
    hooks_path = PROJECT_ROOT / "src" / "amplifier_routing_matrix" / "hooks"
    assert hooks_path.is_dir(), f"hooks/ directory not found at {hooks_path}"


def test_routing_directory_exists() -> None:
    """src/amplifier_routing_matrix/routing/ directory must exist."""
    routing_path = PROJECT_ROOT / "src" / "amplifier_routing_matrix" / "routing"
    assert routing_path.is_dir(), f"routing/ directory not found at {routing_path}"


def test_context_directory_exists() -> None:
    """src/amplifier_routing_matrix/context/ directory must exist."""
    context_path = PROJECT_ROOT / "src" / "amplifier_routing_matrix" / "context"
    assert context_path.is_dir(), f"context/ directory not found at {context_path}"


def test_routing_hook_importable() -> None:
    """amplifier_routing_matrix.hooks.routing.RoutingHook must be importable."""
    from amplifier_routing_matrix.hooks.routing import RoutingHook  # type: ignore[import-untyped]  # noqa: F401


def test_matrix_loader_importable() -> None:
    """amplifier_routing_matrix.hooks.matrix_loader must be importable."""
    from amplifier_routing_matrix.hooks.matrix_loader import (  # type: ignore[import-untyped]  # noqa: F401
        load_matrix,
        compose_matrix,
        validate_matrix,
    )


def test_resolver_importable() -> None:
    """amplifier_routing_matrix.hooks.resolver must be importable."""
    from amplifier_routing_matrix.hooks.resolver import (  # type: ignore[import-untyped]  # noqa: F401
        resolve_model_role,
        find_provider_by_type,
    )


@pytest.mark.skipif(
    shutil.which("amplifier-routing-matrix-serve") is None,
    reason="Package not installed as tool",
)
def test_entry_point_available() -> None:
    """amplifier-routing-matrix-serve must be installed as a console script.

    Checks for the script in the same bin directory as the current Python
    executable, which covers both venv and global installs.

    Note: We do NOT execute the server here because it reads from stdin
    and would block indefinitely.  Existence + executability is the right
    assertion for a scaffolding test.
    """
    bin_dir = Path(sys.executable).parent
    serve_script = bin_dir / "amplifier-routing-matrix-serve"
    assert serve_script.exists(), (
        f"amplifier-routing-matrix-serve not found at {serve_script}. "
        "Run `uv pip install -e .` to install it."
    )
    assert serve_script.is_file(), f"{serve_script} is not a regular file"
    assert os.access(serve_script, os.X_OK), f"{serve_script} is not executable"
