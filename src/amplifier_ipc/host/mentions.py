"""Mention resolution — parse, resolve, and load @namespace:path references.

Provides:

* :func:`parse_mentions` — regex extraction of ``@namespace:path`` tokens from
  text, excluding code blocks, fenced blocks, and inline code.
* :class:`MentionResolver` — async callable protocol for mention resolution.
* :class:`NamespaceResolver` — resolves ``@namespace:path`` via ``content.read`` RPC.
* :class:`WorkingDirResolver` — resolves ``@~/``, ``@user:``, ``@project:``
  via local filesystem.
* :class:`MentionResolverChain` — ordered list of resolvers, first non-None wins.
* :func:`resolve_and_load` — recursive loader with SHA-256 dedup and depth limit.
"""

from __future__ import annotations

import hashlib  # noqa: F401 — used by resolve_and_load (future task)
import logging
import re
from dataclasses import dataclass  # noqa: F401 — used by resolver classes (future task)
from pathlib import Path  # noqa: F401 — used by WorkingDirResolver (future task)
from typing import Any, Protocol  # noqa: F401 — used by MentionResolver protocol (future task)

from amplifier_ipc.host.service_index import ServiceIndex  # noqa: F401 — used by NamespaceResolver (future task)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mention parsing
# ---------------------------------------------------------------------------

# Pattern: @ followed by word chars, colons, slashes, dots, hyphens, tildes.
# Negative lookbehind excludes email addresses (word@domain → the @ is preceded by
# alphanumeric chars, so we skip those).
_MENTION_RE = re.compile(
    r"(?<![a-zA-Z0-9._%+-])"  # not preceded by email-address characters
    r"@([a-zA-Z0-9_:./\~-]+)"
)


def _remove_code_blocks(text: str) -> str:
    """Remove fenced and inline code blocks from *text*.

    Fenced code blocks (````...````) must start at the beginning of a line
    per CommonMark spec.  Inline code (single backticks) is also removed,
    but adjacent triple-backtick sequences (like ``(```)``) are preserved.
    """
    # Remove fenced code blocks — ``` must be at start of line (or start of text)
    text = re.sub(
        r"(?:^|\n)```[^\n]*\n.*?(?:^|\n)```",
        "\n",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    # Remove inline code — single backticks, avoiding triple-backtick sequences
    text = re.sub(r"(?<!`)`(?!`)[^`]+(?<!`)`(?!`)", "", text)
    return text


def parse_mentions(text: str) -> list[str]:
    """Extract ``@namespace:path`` mentions from *text*, excluding code blocks.

    Returns unique mentions (including ``@`` prefix) in order of first
    appearance.  Mentions inside fenced code blocks, inline code, and
    email addresses are excluded.
    """
    text_clean = _remove_code_blocks(text)
    matches = _MENTION_RE.findall(text_clean)

    seen: set[str] = set()
    result: list[str] = []
    for match in matches:
        mention = f"@{match}"
        if mention not in seen:
            seen.add(mention)
            result.append(mention)
    return result
