"""Service describe verification — verifies component discovery and content discovery."""

from __future__ import annotations

from amplifier_ipc.protocol.discovery import scan_content, scan_package


def test_discovers_no_tools() -> None:
    """amplifier_recipes must report no tools (content-only service)."""
    components = scan_package("amplifier_recipes")
    assert components.get("tools", []) == [], (
        f"Expected no tools, got: {components.get('tools', [])}"
    )


def test_discovers_no_hooks() -> None:
    """amplifier_recipes must report no hooks (content-only service)."""
    components = scan_package("amplifier_recipes")
    assert components.get("hooks", []) == [], (
        f"Expected no hooks, got: {components.get('hooks', [])}"
    )


def test_discovers_no_orchestrators() -> None:
    """amplifier_recipes must report no orchestrators (content-only service)."""
    components = scan_package("amplifier_recipes")
    assert components.get("orchestrators", []) == [], (
        f"Expected no orchestrators, got: {components.get('orchestrators', [])}"
    )


def test_discovers_no_context_managers() -> None:
    """amplifier_recipes must report no context_managers (content-only service)."""
    components = scan_package("amplifier_recipes")
    assert components.get("context_managers", []) == [], (
        f"Expected no context_managers, got: {components.get('context_managers', [])}"
    )


def test_discovers_no_providers() -> None:
    """amplifier_recipes must report no providers (content-only service)."""
    components = scan_package("amplifier_recipes")
    assert components.get("providers", []) == [], (
        f"Expected no providers, got: {components.get('providers', [])}"
    )


def test_discovers_content() -> None:
    """amplifier_recipes must expose at least 1 content file via scan_content."""
    paths = scan_content("amplifier_recipes")
    assert len(paths) > 0, "Expected at least one content file, got none"


def test_content_includes_context_files() -> None:
    """scan_content must include files from the context/ directory."""
    paths = scan_content("amplifier_recipes")
    context_files = [p for p in paths if p.startswith("context/")]
    assert len(context_files) >= 1, (
        f"Expected >= 1 context file, got: {context_files}"
    )


def test_content_includes_recipe_files() -> None:
    """scan_content must include files from the recipes/ directory."""
    paths = scan_content("amplifier_recipes")
    recipe_files = [p for p in paths if p.startswith("recipes/")]
    assert len(recipe_files) >= 1, (
        f"Expected >= 1 recipe file, got: {recipe_files}"
    )
