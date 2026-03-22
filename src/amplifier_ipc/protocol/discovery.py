"""Component and content discovery for Amplifier IPC packages.

Scans conventional package directories for decorated component classes and
content files, enabling automatic registration at server startup.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

COMPONENT_DIRS = ["tools", "hooks", "orchestrators", "context_managers", "providers"]
CONTENT_DIRS = ["agents", "context", "behaviors", "recipes", "sessions"]


def _get_package_dir(package_name: str) -> Path:
    """Import *package_name* and return the directory that contains it."""
    mod = importlib.import_module(package_name)
    return Path(mod.__file__).parent  # type: ignore[arg-type]


def scan_package(package_name: str) -> dict[str, list[type]]:
    """Scan COMPONENT_DIRS subdirectories for classes marked with __amplifier_component__.

    For each .py file (skipping __init__.py) found in any of the conventional
    component subdirectories, the module is imported and all classes defined in
    that module (``obj.__module__ == mod.__name__``) that carry the
    ``__amplifier_component__`` attribute are collected and grouped by their
    component type string.

    Returns a dict mapping component-type strings to lists of classes.
    Classes are NOT instantiated here — instantiation is deferred until after
    configuration arrives (lazy instantiation for the configuration protocol).
    Import failures are logged as warnings and skipped.
    """
    result: dict[str, list[type]] = {}
    pkg_dir = _get_package_dir(package_name)

    for dir_name in COMPONENT_DIRS:
        component_dir = pkg_dir / dir_name
        if not component_dir.exists():
            continue

        for py_file in component_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue

            module_name = f"{package_name}.{dir_name}.{py_file.stem}"
            try:
                mod = importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to import %s: %s", module_name, exc)
                continue

            for _, obj in inspect.getmembers(mod, inspect.isclass):
                if obj.__module__ != mod.__name__:
                    continue

                component_type: str | None = getattr(
                    obj, "__amplifier_component__", None
                )
                if component_type is None:
                    continue

                result.setdefault(component_type, []).append(obj)

    return result


def scan_content(package_name: str) -> list[str]:
    """Scan CONTENT_DIRS subdirectories recursively for all non-init files.

    Returns a list of path strings relative to the package root directory,
    using forward slashes (``posixpath`` style on all platforms).
    ``__init__.py`` files are excluded.
    """
    pkg_dir = _get_package_dir(package_name)
    content_files: list[str] = []

    for dir_name in CONTENT_DIRS:
        content_dir = pkg_dir / dir_name
        if not content_dir.exists():
            continue

        for f in sorted(content_dir.rglob("*")):
            if f.is_file() and f.name != "__init__.py":
                rel = f.relative_to(pkg_dir)
                content_files.append(rel.as_posix())

    return content_files
