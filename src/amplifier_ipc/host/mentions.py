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
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from amplifier_ipc.host.service_index import ServiceIndex

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resolver protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class MentionResolver(Protocol):
    """Async callable that resolves a mention string to its content.

    Returns the content string on success, or ``None`` if the mention cannot
    be resolved (unknown namespace, invalid format, RPC error, etc.).
    """

    async def __call__(self, mention: str) -> str | None:  # pragma: no cover
        ...


# ---------------------------------------------------------------------------
# NamespaceResolver
# ---------------------------------------------------------------------------


class NamespaceResolver:
    """Resolves ``@namespace:path`` mentions via ``content.read`` RPC.

    Looks up the namespace in the service registry's content services, then
    delegates to the matching service's client to read the file content.

    Gracefully returns ``None`` on any error (unknown namespace, RPC failure,
    missing key, etc.) to avoid crashing the caller.
    """

    def __init__(self, registry: ServiceIndex, services: dict[str, Any]) -> None:
        self._registry = registry
        self._services = services

    async def __call__(self, mention: str) -> str | None:
        """Resolve *mention* to its content, or return ``None`` on failure."""
        # Strip optional leading @
        ref = mention.lstrip("@")

        # Must contain a colon to be a namespace:path mention
        if ":" not in ref:
            return None

        namespace, path = ref.split(":", 1)

        # Check namespace is registered as a content service
        content_services = self._registry.get_content_services()
        if namespace not in content_services:
            return None

        try:
            service = self._services[namespace]
            result = await service.client.request("content.read", {"path": path})
            return result["content"]
        except Exception:
            logger.warning("NamespaceResolver: failed to resolve %r", mention)
            return None


# ---------------------------------------------------------------------------
# WorkingDirResolver
# ---------------------------------------------------------------------------


class WorkingDirResolver:
    """Resolves ``@~/``, ``@user:``, and ``@project:`` mentions from the local filesystem.

    * ``@~/path`` — resolves relative to *home_dir*
    * ``@user:path`` — resolves relative to ``<home_dir>/.amplifier/``
    * ``@project:path`` — resolves relative to ``<working_dir>/.amplifier/``

    Returns ``None`` for unrecognised prefixes or files that cannot be read.
    """

    def __init__(self, working_dir: Path, home_dir: Path | None = None) -> None:
        self._working_dir = working_dir
        self._home_dir = home_dir if home_dir is not None else Path.home()

    def __call__(self, mention: str) -> str | None:
        """Resolve *mention* to its file content, or return ``None`` on failure."""
        ref = mention.lstrip("@")

        if ref.startswith("~/"):
            file_path = self._home_dir / ref[2:]
        elif ref.startswith("user:"):
            file_path = self._home_dir / ".amplifier" / ref[len("user:") :]
        elif ref.startswith("project:"):
            file_path = self._working_dir / ".amplifier" / ref[len("project:") :]
        else:
            return None

        try:
            return file_path.read_text()
        except (FileNotFoundError, OSError):
            logger.warning("WorkingDirResolver: could not read file %r", str(file_path))
            return None


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
