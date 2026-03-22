"""Content reading utilities with path traversal security for Amplifier IPC packages."""

from __future__ import annotations

from pathlib import Path


def read_content(package_dir: Path, relative_path: str) -> str | None:
    """Read a content file from *package_dir*, enforcing path traversal security.

    Resolves *relative_path* against *package_dir*, then checks that the
    resolved target is still within *package_dir*.  Returns ``None`` if the
    path escapes the package root or does not point to a regular file.
    Otherwise reads and returns the UTF-8 text.

    Args:
        package_dir: Absolute path to the package root directory.
        relative_path: A relative path string (e.g. ``"agents/explorer.md"``).

    Returns:
        The file's UTF-8 text content, or ``None`` if the path is unsafe or
        the file does not exist.
    """
    resolved_root = package_dir.resolve()
    target = (package_dir / relative_path).resolve()

    # Security check: resolved target must still be under package_dir
    try:
        target.relative_to(resolved_root)
    except ValueError:
        return None

    if not target.is_file():
        return None

    return target.read_text(encoding="utf-8")
