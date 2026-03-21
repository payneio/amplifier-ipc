"""Path policy for project slug and session directories.

All functions are pure path computations — no directory creation occurs.
"""

from __future__ import annotations

from pathlib import Path

AMPLIFIER_DIR = ".amplifier"


def is_running_from_home() -> bool:
    """Return True if the current working directory is the user's home directory."""
    return Path.cwd() == Path.home()


def get_project_slug() -> str:
    """Return the project slug for the current working directory.

    Returns 'global' when running from the home directory, otherwise returns
    the name of the current directory.
    """
    if is_running_from_home():
        return "global"
    return Path.cwd().name


def get_projects_base_dir() -> Path:
    """Return the base directory for all projects: ~/.amplifier/projects/."""
    return Path.home() / AMPLIFIER_DIR / "projects"


def get_sessions_base_dir() -> Path:
    """Return the base directory for sessions in the current project.

    Layout: ~/.amplifier/projects/<project-slug>/sessions/
    """
    return get_projects_base_dir() / get_project_slug() / "sessions"


def get_session_dir(session_id: str) -> Path:
    """Return the session directory for the given session ID.

    Layout: ~/.amplifier/projects/<project-slug>/sessions/<session-id>/
    """
    return get_sessions_base_dir() / session_id


def get_repl_history_path() -> Path:
    """Return the REPL history file path for the current project.

    Layout: ~/.amplifier/projects/<project-slug>/repl_history
    """
    return get_projects_base_dir() / get_project_slug() / "repl_history"
