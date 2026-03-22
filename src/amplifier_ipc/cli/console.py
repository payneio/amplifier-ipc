"""Shared Rich Console singleton and custom Markdown renderer."""

from __future__ import annotations

from typing import Any

from rich.console import Console as RichConsole
from rich.console import ConsoleOptions, RenderResult
from rich.errors import MarkupError
from rich.markdown import Heading as RichHeading
from rich.markdown import Markdown as RichMarkdown
from rich.segment import Segment

__all__ = ["console", "Markdown", "LeftAlignedHeading"]


class LeftAlignedHeading(RichHeading):
    """Rich Heading subclass with hierarchical styling, always left-aligned.

    Styling:
    - H1: italic + underlined, with a blank line before and after
    - H2: bold, with a blank line before
    - H3–H6: dim
    """

    def __rich_console__(
        self, console: RichConsole, options: ConsoleOptions
    ) -> RenderResult:
        text = self.text.copy()
        # Force left alignment on all heading levels
        text.justify = "left"

        if self.tag == "h1":
            text.stylize("italic underline")
            yield Segment("\n")
            yield text
            yield Segment("\n")
        elif self.tag == "h2":
            text.stylize("bold")
            yield Segment("\n")
            yield text
        else:
            # h3-h6: dim
            text.stylize("dim")
            yield text


# ---------------------------------------------------------------------------
# Markdown subclass — overrides heading_open element
# ---------------------------------------------------------------------------


class Markdown(RichMarkdown):
    """Rich Markdown subclass with left-aligned headings."""

    elements = {
        **RichMarkdown.elements,
        "heading_open": LeftAlignedHeading,
    }


# ---------------------------------------------------------------------------
# Console singleton with MarkupError safety wrapper
# ---------------------------------------------------------------------------


def _make_safe_console() -> RichConsole:
    """Create a Console instance and wrap its print method for MarkupError safety."""
    _console = RichConsole(stderr=True)

    # Grab the original unbound print method
    _original_print = _console.print

    def _safe_print(*args: Any, **kwargs: Any) -> None:
        """Wrap Console.print to survive unescaped Rich markup."""
        try:
            _original_print(*args, **kwargs)
        except MarkupError:
            # Retry without markup processing
            kwargs.pop("markup", None)
            kwargs.pop("highlight", None)
            _original_print(*args, markup=False, highlight=False, **kwargs)

    _safe_print._is_safe_wrapper = True  # type: ignore[attr-defined]
    # Guard in case this console instance is somehow pre-wrapped in future.
    if not getattr(_console.print, "_is_safe_wrapper", False):
        _console.print = _safe_print  # type: ignore[method-assign]
    return _console


console: RichConsole = _make_safe_console()
