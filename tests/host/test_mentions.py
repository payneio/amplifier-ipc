"""Tests for the mentions module — parsing, resolving, and loading @mentions."""

from __future__ import annotations

from amplifier_ipc.host.mentions import parse_mentions


# ---------------------------------------------------------------------------
# Tests: parse_mentions
# ---------------------------------------------------------------------------


def test_parse_mentions_extracts_namespace_path() -> None:
    """Extracts @namespace:path mentions from plain text."""
    result = parse_mentions("Load @foundation:context/common.md please")
    assert result == ["@foundation:context/common.md"]


def test_parse_mentions_multiple() -> None:
    """Extracts multiple distinct mentions preserving order."""
    text = "Use @foundation:context/a.md and @superpowers:context/b.md here"
    result = parse_mentions(text)
    assert result == ["@foundation:context/a.md", "@superpowers:context/b.md"]


def test_parse_mentions_excludes_fenced_code_blocks() -> None:
    """Mentions inside fenced code blocks are excluded."""
    text = "Before\n```\n@foundation:context/code.md\n```\nAfter @real:mention.md"
    result = parse_mentions(text)
    assert result == ["@real:mention.md"]


def test_parse_mentions_excludes_inline_code() -> None:
    """Mentions inside inline code are excluded."""
    text = "Use `@foundation:context/code.md` but also @real:mention.md"
    result = parse_mentions(text)
    assert result == ["@real:mention.md"]


def test_parse_mentions_deduplicates() -> None:
    """Duplicate mentions appear only once, preserving first occurrence order."""
    text = "@a:b.md and @a:b.md again"
    result = parse_mentions(text)
    assert result == ["@a:b.md"]


def test_parse_mentions_excludes_email_addresses() -> None:
    """Email-like patterns are not treated as mentions."""
    text = "Contact user@example.com and load @foundation:context/x.md"
    result = parse_mentions(text)
    assert result == ["@foundation:context/x.md"]


def test_parse_mentions_handles_tilde_path() -> None:
    """Tilde-prefixed paths like @~/path are extracted."""
    result = parse_mentions("Load @~/docs/AGENTS.md")
    assert result == ["@~/docs/AGENTS.md"]


def test_parse_mentions_handles_special_prefixes() -> None:
    """@user: and @project: prefixes are extracted."""
    text = "Load @user:skills/foo.md and @project:AGENTS.md"
    result = parse_mentions(text)
    assert result == ["@user:skills/foo.md", "@project:AGENTS.md"]


def test_parse_mentions_empty_text() -> None:
    """Empty text returns empty list."""
    assert parse_mentions("") == []


def test_parse_mentions_no_mentions() -> None:
    """Text with no mentions returns empty list."""
    assert parse_mentions("Just plain text with no at-signs of interest.") == []
