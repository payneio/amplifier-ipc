"""Tests for component and content discovery."""

from __future__ import annotations

import sys
from pathlib import Path

from amplifier_ipc.protocol.discovery import scan_content, scan_package


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _create_mock_package(tmp_path: Path, pkg_name: str) -> Path:
    """Create a minimal mock package in tmp_path and return its directory."""
    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    return pkg_dir


# ---------------------------------------------------------------------------
# scan_package tests
# ---------------------------------------------------------------------------


def test_scan_package_finds_tools(tmp_path: Path) -> None:
    """scan_package finds @tool decorated classes in tools/ directory."""
    pkg_dir = _create_mock_package(tmp_path, "mock_tools_pkg")
    tools_dir = pkg_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "adder.py").write_text(
        "from amplifier_ipc.protocol.decorators import tool\n\n"
        "@tool\n"
        "class Adder:\n"
        "    pass\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        result = scan_package("mock_tools_pkg")
        assert "tool" in result
        assert len(result["tool"]) == 1
        assert result["tool"][0].__class__.__name__ == "Adder"
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules.keys()):
            if key == "mock_tools_pkg" or key.startswith("mock_tools_pkg."):
                del sys.modules[key]


def test_scan_package_finds_hooks(tmp_path: Path) -> None:
    """scan_package finds @hook decorated classes in hooks/ directory."""
    pkg_dir = _create_mock_package(tmp_path, "mock_hooks_pkg")
    hooks_dir = pkg_dir / "hooks"
    hooks_dir.mkdir()
    (hooks_dir / "__init__.py").write_text("")
    (hooks_dir / "approval.py").write_text(
        "from amplifier_ipc.protocol.decorators import hook\n\n"
        "@hook(events=['on_event'])\n"
        "class ApprovalHook:\n"
        "    pass\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        result = scan_package("mock_hooks_pkg")
        assert "hook" in result
        assert len(result["hook"]) == 1
        assert result["hook"][0].__class__.__name__ == "ApprovalHook"
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules.keys()):
            if key == "mock_hooks_pkg" or key.startswith("mock_hooks_pkg."):
                del sys.modules[key]


def test_scan_package_finds_multiple_types(tmp_path: Path) -> None:
    """scan_package finds components across tools/ and orchestrators/ directories."""
    pkg_dir = _create_mock_package(tmp_path, "mock_multi_pkg")

    tools_dir = pkg_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "calculator.py").write_text(
        "from amplifier_ipc.protocol.decorators import tool\n\n"
        "@tool\n"
        "class Calculator:\n"
        "    pass\n"
    )

    orch_dir = pkg_dir / "orchestrators"
    orch_dir.mkdir()
    (orch_dir / "__init__.py").write_text("")
    (orch_dir / "main.py").write_text(
        "from amplifier_ipc.protocol.decorators import orchestrator\n\n"
        "@orchestrator\n"
        "class MainOrchestrator:\n"
        "    pass\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        result = scan_package("mock_multi_pkg")
        assert "tool" in result
        assert "orchestrator" in result
        assert len(result["tool"]) == 1
        assert len(result["orchestrator"]) == 1
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules.keys()):
            if key == "mock_multi_pkg" or key.startswith("mock_multi_pkg."):
                del sys.modules[key]


def test_scan_package_empty_package(tmp_path: Path) -> None:
    """scan_package returns empty result for a package with no component directories."""
    _create_mock_package(tmp_path, "mock_empty_pkg")

    sys.path.insert(0, str(tmp_path))
    try:
        result = scan_package("mock_empty_pkg")
        total = sum(len(v) for v in result.values())
        assert total == 0
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules.keys()):
            if key == "mock_empty_pkg" or key.startswith("mock_empty_pkg."):
                del sys.modules[key]


# ---------------------------------------------------------------------------
# scan_content tests
# ---------------------------------------------------------------------------


def test_scan_content_finds_files(tmp_path: Path) -> None:
    """scan_content finds files in agents/, context/, and behaviors/ directories."""
    pkg_dir = _create_mock_package(tmp_path, "mock_content_pkg")

    agents_dir = pkg_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "explorer.md").write_text("# Explorer Agent")

    context_dir = pkg_dir / "context"
    context_dir.mkdir()
    (context_dir / "rules.md").write_text("# Rules")

    behaviors_dir = pkg_dir / "behaviors"
    behaviors_dir.mkdir()
    (behaviors_dir / "default.yaml").write_text("behavior: default")

    sys.path.insert(0, str(tmp_path))
    try:
        result = scan_content("mock_content_pkg")
        result_set = set(result)
        assert "agents/explorer.md" in result_set
        assert "context/rules.md" in result_set
        assert "behaviors/default.yaml" in result_set
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules.keys()):
            if key == "mock_content_pkg" or key.startswith("mock_content_pkg."):
                del sys.modules[key]


def test_scan_content_empty_package(tmp_path: Path) -> None:
    """scan_content returns empty list for a package with no content directories."""
    _create_mock_package(tmp_path, "mock_empty_content_pkg")

    sys.path.insert(0, str(tmp_path))
    try:
        result = scan_content("mock_empty_content_pkg")
        assert result == []
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules.keys()):
            if key == "mock_empty_content_pkg" or key.startswith(
                "mock_empty_content_pkg."
            ):
                del sys.modules[key]
