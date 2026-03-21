"""Shared default constants for search tools.

DEFAULT_EXCLUSIONS is used by both GrepTool and GlobTool to filter out
common non-source directories. Centralised here to prevent the two tools
from drifting out of sync if a new exclusion is ever added.
"""

DEFAULT_EXCLUSIONS: list[str] = [
    "node_modules",
    ".venv",
    "venv",
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",
    "vendor",
    ".gradle",
    ".idea",
    ".vscode",
    "coverage",
    ".nyc_output",
]
