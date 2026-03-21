"""Path validation for filesystem operations.

Provides centralized allow/deny path checking logic.
Key principle: DENY always takes priority over ALLOW.
"""

from pathlib import Path


def is_in_path_list(target: Path, path_list: list[str]) -> bool:
    """Check if target path is within any path in the list."""
    resolved = target.resolve()
    for p in path_list:
        p_resolved = Path(p).expanduser().resolve()
        if p_resolved == resolved or p_resolved in resolved.parents:
            return True
    return False


def is_path_allowed(
    path: Path,
    allowed_paths: list[str],
    denied_paths: list[str],
) -> tuple[bool, str | None]:
    """Check if path is allowed for writing.

    Validation order:
    1. Check denied_paths first - if match, DENY
    2. Check allowed_paths - if match, ALLOW
    3. Default - DENY (not in allowed list)

    Returns:
        Tuple of (allowed: bool, error_message: str | None)
    """
    resolved = path.resolve()

    if denied_paths and is_in_path_list(resolved, denied_paths):
        return (False, f"Access denied: {path} is within denied directories")

    if is_in_path_list(resolved, allowed_paths):
        return (True, None)

    return (False, f"Access denied: {path} is not within allowed write paths")
