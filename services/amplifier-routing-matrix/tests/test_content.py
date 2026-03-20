"""Tests for content files — verifies all content directories are discoverable
and routing matrix YAML files are accessible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_ipc_protocol.discovery import scan_content


PROJECT_ROOT = Path(__file__).parent.parent
PACKAGE_DIR = PROJECT_ROOT / "src" / "amplifier_routing_matrix"

EXPECTED_ROUTING_MATRICES = [
    "anthropic",
    "balanced",
    "copilot",
    "economy",
    "gemini",
    "openai",
    "quality",
]


@pytest.fixture(scope="module")
def content_files() -> list[str]:
    """Scan amplifier_routing_matrix content once for the entire test module."""
    return scan_content("amplifier_routing_matrix")


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


def test_context_routing_instructions_present(content_files: list[str]) -> None:
    """context/routing-instructions.md must be present in discovered content."""
    assert "context/routing-instructions.md" in content_files, (
        f"Expected 'context/routing-instructions.md' in content files. "
        f"Found context files: {_files_in_dir(content_files, 'context')}"
    )


def test_context_role_definitions_present(content_files: list[str]) -> None:
    """context/role-definitions.md must be present in discovered content."""
    assert "context/role-definitions.md" in content_files, (
        f"Expected 'context/role-definitions.md' in content files. "
        f"Found context files: {_files_in_dir(content_files, 'context')}"
    )


def test_context_files_are_non_empty(content_files: list[str]) -> None:
    """All discovered context files must be non-empty."""
    context_files = _files_in_dir(content_files, "context")
    for rel_path in context_files:
        abs_path = PACKAGE_DIR / rel_path.replace("context/", "context/", 1)
        assert abs_path.exists(), f"Context file does not exist: {abs_path}"
        content = abs_path.read_text(encoding="utf-8").strip()
        assert len(content) > 0, f"Context file is empty: {rel_path}"


# ---------------------------------------------------------------------------
# Routing matrix YAML files
# ---------------------------------------------------------------------------


def test_routing_directory_has_yaml_files() -> None:
    """The routing/ directory must contain at least one YAML file."""
    routing_dir = PACKAGE_DIR / "routing"
    yaml_files = list(routing_dir.glob("*.yaml"))
    assert len(yaml_files) >= 1, (
        f"Expected >= 1 YAML file in routing/, found {len(yaml_files)}"
    )


def test_routing_directory_has_all_expected_matrices() -> None:
    """The routing/ directory must contain all 7 expected matrix files."""
    routing_dir = PACKAGE_DIR / "routing"
    for name in EXPECTED_ROUTING_MATRICES:
        matrix_path = routing_dir / f"{name}.yaml"
        assert matrix_path.exists(), (
            f"Expected routing matrix '{name}.yaml' not found at {matrix_path}"
        )


@pytest.mark.parametrize("matrix_name", EXPECTED_ROUTING_MATRICES)
def test_routing_matrix_is_loadable(matrix_name: str) -> None:
    """Each routing matrix YAML file must be loadable and contain required fields."""
    from amplifier_routing_matrix.hooks.matrix_loader import (  # type: ignore[import-untyped]
        load_matrix,
        validate_matrix,
    )

    routing_dir = PACKAGE_DIR / "routing"
    matrix_path = routing_dir / f"{matrix_name}.yaml"

    matrix = load_matrix(matrix_path)
    assert isinstance(matrix, dict), (
        f"Matrix '{matrix_name}' must be a YAML mapping, got {type(matrix)}"
    )
    assert "name" in matrix, f"Matrix '{matrix_name}' missing 'name' field"
    assert "roles" in matrix, f"Matrix '{matrix_name}' missing 'roles' field"

    errors = validate_matrix(matrix)
    assert len(errors) == 0, f"Matrix '{matrix_name}' failed validation:\n" + "\n".join(
        errors
    )


@pytest.mark.parametrize("matrix_name", EXPECTED_ROUTING_MATRICES)
def test_routing_matrix_has_required_roles(matrix_name: str) -> None:
    """Each routing matrix must define the required 'general' and 'fast' roles."""
    from amplifier_routing_matrix.hooks.matrix_loader import load_matrix  # type: ignore[import-untyped]

    routing_dir = PACKAGE_DIR / "routing"
    matrix = load_matrix(routing_dir / f"{matrix_name}.yaml")
    roles = matrix.get("roles", {})

    assert "general" in roles, f"Matrix '{matrix_name}' missing required 'general' role"
    assert "fast" in roles, f"Matrix '{matrix_name}' missing required 'fast' role"


def test_balanced_matrix_is_default_and_loadable() -> None:
    """The balanced matrix (default) must be loadable by the RoutingHook."""
    from amplifier_routing_matrix.hooks.routing import RoutingHook  # type: ignore[import-untyped]

    hook = RoutingHook()
    assert hook.base_matrix, "RoutingHook.base_matrix must be non-empty"
    assert hook.base_matrix.get("name") == "balanced", (
        f"Expected default matrix name 'balanced', got: {hook.base_matrix.get('name')}"
    )
    assert hook.effective_matrix, "RoutingHook.effective_matrix must be non-empty"
