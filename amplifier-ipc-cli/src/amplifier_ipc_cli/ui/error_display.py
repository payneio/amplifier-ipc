"""Error display formatting for generic exceptions.

Provides display_error() which renders a Rich Panel for generic exceptions.
This is a simplified stub with no amplifier_lite.models dependency.
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

from rich.panel import Panel

if TYPE_CHECKING:
    from rich.console import Console

__all__ = ["display_error"]


def display_error(
    console: Console,
    error: Exception,
    verbose: bool = False,
) -> None:
    """Display a formatted Rich Panel for a generic exception.

    Args:
        console: Rich Console to print to.
        error:   The exception to display.
        verbose: When True, also prints the full traceback.
    """
    title = type(error).__name__
    message = str(error) or "An unexpected error occurred."

    panel = Panel(
        message,
        title=title,
        border_style="red",
    )
    console.print(panel)

    if verbose:
        console.print(traceback.format_exc())
