"""Scaffolding tests for amplifier-providers package.

Verifies the project structure, importability, and entry point configuration.
"""

from __future__ import annotations

import importlib
from pathlib import Path


def test_package_importable() -> None:
    """Package must be importable."""
    mod = importlib.import_module("amplifier_providers")
    assert mod is not None


def test_package_version() -> None:
    """Package must expose __version__ == '0.1.0'."""
    import amplifier_providers

    assert amplifier_providers.__version__ == "0.1.0"


def test_main_module_exists() -> None:
    """__main__.py must exist in the package."""
    import amplifier_providers

    pkg_dir = Path(amplifier_providers.__file__).parent  # type: ignore[arg-type]
    main_file = pkg_dir / "__main__.py"
    assert main_file.exists(), f"__main__.py not found at {main_file}"


def test_main_module_importable() -> None:
    """amplifier_providers.__main__ must be importable."""
    mod = importlib.import_module("amplifier_providers.__main__")
    assert hasattr(mod, "main"), "__main__ must expose a main() function"


def test_providers_directory_exists() -> None:
    """providers/ subdirectory must exist inside the package."""
    import amplifier_providers

    pkg_dir = Path(amplifier_providers.__file__).parent  # type: ignore[arg-type]
    providers_dir = pkg_dir / "providers"
    assert providers_dir.is_dir(), f"providers/ dir not found at {providers_dir}"


def test_providers_has_init() -> None:
    """providers/__init__.py must exist."""
    import amplifier_providers

    pkg_dir = Path(amplifier_providers.__file__).parent  # type: ignore[arg-type]
    init_file = pkg_dir / "providers" / "__init__.py"
    assert init_file.exists(), f"providers/__init__.py not found at {init_file}"


def test_entry_point_defined_in_pyproject() -> None:
    """Entry point 'amplifier-providers-serve' must be declared in pyproject.toml."""
    import amplifier_providers

    pkg_dir = Path(amplifier_providers.__file__).parent  # type: ignore[arg-type]
    # pyproject.toml is at the service root (3 levels up: pkg -> src -> service root)
    pyproject = pkg_dir.parent.parent / "pyproject.toml"
    assert pyproject.exists(), f"pyproject.toml not found at {pyproject}"

    content = pyproject.read_text()
    assert "amplifier-providers-serve" in content, (
        "Entry point 'amplifier-providers-serve' not found in pyproject.toml"
    )
