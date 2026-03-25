"""Tests for the mentions module — parsing, resolving, and loading @mentions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

import hashlib

from amplifier_ipc.host.mentions import (
    MentionResolverChain,
    NamespaceResolver,
    ResolvedContent,
    WorkingDirResolver,
    parse_mentions,
    resolve_and_load,
)
from amplifier_ipc.host.service_index import ServiceIndex


# ---------------------------------------------------------------------------
# Helpers for NamespaceResolver tests
# ---------------------------------------------------------------------------


class FakeClient:
    """In-memory fake client that serves content.read requests."""

    def __init__(self, files: dict[str, str]) -> None:
        self._files = files

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "content.read":
            path = params["path"]
            if path in self._files:
                return {"content": self._files[path]}
            raise KeyError(f"File not found: {path}")
        raise NotImplementedError(f"Unknown method: {method}")


class FakeService:
    """Wraps a FakeClient to look like a real service."""

    def __init__(self, client: FakeClient) -> None:
        self.client = client


def _build_registry_and_services() -> tuple[ServiceIndex, dict[str, Any]]:
    """Build a ServiceIndex and services dict for testing.

    Creates:
    - foundation: serves agents/explorer.md, context/shared/common.md
    - superpowers: serves context/philosophy.md
    """
    registry = ServiceIndex()

    # Register foundation service
    registry.register(
        "foundation",
        {
            "content": ["agents/explorer.md", "context/shared/common.md"],
        },
    )

    # Register superpowers service
    registry.register(
        "superpowers",
        {
            "content": ["context/philosophy.md"],
        },
    )

    foundation_client = FakeClient(
        {
            "agents/explorer.md": "Explorer agent content",
            "context/shared/common.md": "Common context content",
        }
    )
    superpowers_client = FakeClient(
        {
            "context/philosophy.md": "Philosophy content",
        }
    )

    services: dict[str, Any] = {
        "foundation": FakeService(foundation_client),
        "superpowers": FakeService(superpowers_client),
    }

    return registry, services


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


# ---------------------------------------------------------------------------
# Tests: NamespaceResolver
# ---------------------------------------------------------------------------


async def test_namespace_resolver_resolves_known_namespace() -> None:
    """Resolves a known @namespace:path mention by calling content.read RPC."""
    registry, services = _build_registry_and_services()
    resolver = NamespaceResolver(registry=registry, services=services)
    result = await resolver("@foundation:agents/explorer.md")
    assert result == "Explorer agent content"


async def test_namespace_resolver_returns_none_for_unknown_namespace() -> None:
    """Returns None when namespace is not in the registry."""
    registry, services = _build_registry_and_services()
    resolver = NamespaceResolver(registry=registry, services=services)
    result = await resolver("@unknown:some/path.md")
    assert result is None


async def test_namespace_resolver_returns_none_for_invalid_format() -> None:
    """Returns None when mention has no colon separator (invalid format)."""
    registry, services = _build_registry_and_services()
    resolver = NamespaceResolver(registry=registry, services=services)
    result = await resolver("@nocolon")
    assert result is None


async def test_namespace_resolver_returns_none_on_rpc_error() -> None:
    """Returns None gracefully when the RPC call raises an exception."""
    registry, services = _build_registry_and_services()
    resolver = NamespaceResolver(registry=registry, services=services)
    # Request a path that doesn't exist in the FakeClient
    result = await resolver("@foundation:agents/nonexistent.md")
    assert result is None


async def test_namespace_resolver_strips_at_prefix() -> None:
    """Works with or without the leading @ prefix on the mention string."""
    registry, services = _build_registry_and_services()
    resolver = NamespaceResolver(registry=registry, services=services)
    # Without @ prefix
    result = await resolver("foundation:context/shared/common.md")
    assert result == "Common context content"


# ---------------------------------------------------------------------------
# Tests: WorkingDirResolver
# ---------------------------------------------------------------------------


def test_working_dir_resolver_resolves_tilde_path(tmp_path: Path) -> None:
    """@~/path resolves relative to home_dir."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    (home_dir / "docs").mkdir()
    (home_dir / "docs" / "AGENTS.md").write_text("Home AGENTS content")

    resolver = WorkingDirResolver(working_dir=tmp_path, home_dir=home_dir)
    result = resolver("@~/docs/AGENTS.md")
    assert result == "Home AGENTS content"


def test_working_dir_resolver_resolves_user_path(tmp_path: Path) -> None:
    """@user:path resolves relative to home_dir/.amplifier/."""
    home_dir = tmp_path / "home"
    amplifier_dir = home_dir / ".amplifier"
    (amplifier_dir / "skills").mkdir(parents=True)
    (amplifier_dir / "skills" / "foo.md").write_text("User skill content")

    resolver = WorkingDirResolver(working_dir=tmp_path, home_dir=home_dir)
    result = resolver("@user:skills/foo.md")
    assert result == "User skill content"


def test_working_dir_resolver_resolves_project_path(tmp_path: Path) -> None:
    """@project:path resolves relative to working_dir/.amplifier/."""
    amplifier_dir = tmp_path / ".amplifier"
    amplifier_dir.mkdir()
    (amplifier_dir / "AGENTS.md").write_text("Project AGENTS content")

    resolver = WorkingDirResolver(working_dir=tmp_path)
    result = resolver("@project:AGENTS.md")
    assert result == "Project AGENTS content"


def test_working_dir_resolver_returns_none_for_unhandled(tmp_path: Path) -> None:
    """Returns None for mentions with unrecognised prefixes."""
    resolver = WorkingDirResolver(working_dir=tmp_path)
    result = resolver("@unknown:some/path.md")
    assert result is None


def test_working_dir_resolver_returns_none_for_missing_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Returns None (with warning) when the resolved file does not exist."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    resolver = WorkingDirResolver(working_dir=tmp_path, home_dir=home_dir)
    with caplog.at_level(logging.WARNING, logger="amplifier_ipc.host.mentions"):
        result = resolver("@~/nonexistent.md")
    assert result is None
    assert "nonexistent.md" in caplog.text


# ---------------------------------------------------------------------------
# Helpers for MentionResolverChain tests
# ---------------------------------------------------------------------------


class FakeSyncResolver:
    """Sync resolver that returns a fixed result for every mention."""

    def __init__(self, result: str | None) -> None:
        self._result = result

    def __call__(self, mention: str) -> str | None:
        return self._result


# ---------------------------------------------------------------------------
# Tests: MentionResolverChain
# ---------------------------------------------------------------------------


def test_chain_empty() -> None:
    """Empty chain returns None for any mention."""
    chain = MentionResolverChain()
    assert chain.resolve("@ns:path.md") is None


def test_chain_resolve_first_wins() -> None:
    """First resolver returning non-None wins; subsequent resolvers are not needed."""
    r1 = FakeSyncResolver("first result")
    r2 = FakeSyncResolver("second result")
    chain = MentionResolverChain(resolvers=[r1, r2])  # type: ignore[arg-type]
    assert chain.resolve("@ns:path.md") == "first result"


def test_chain_resolve_skips_none() -> None:
    """Resolvers returning None are skipped; the next resolver is tried."""
    r1 = FakeSyncResolver(None)
    r2 = FakeSyncResolver("second result")
    chain = MentionResolverChain(resolvers=[r1, r2])  # type: ignore[arg-type]
    assert chain.resolve("@ns:path.md") == "second result"


def test_chain_resolve_all_none() -> None:
    """Returns None when all resolvers in the chain return None."""
    r1 = FakeSyncResolver(None)
    r2 = FakeSyncResolver(None)
    chain = MentionResolverChain(resolvers=[r1, r2])  # type: ignore[arg-type]
    assert chain.resolve("@ns:path.md") is None


def test_chain_prepend() -> None:
    """prepend inserts a resolver at the front (highest priority)."""
    r_existing = FakeSyncResolver("existing")
    chain = MentionResolverChain(resolvers=[r_existing])  # type: ignore[arg-type]
    r_prepended = FakeSyncResolver("prepended")
    chain.prepend(r_prepended)  # type: ignore[arg-type]
    assert chain.resolve("@ns:path.md") == "prepended"


def test_chain_append() -> None:
    """append adds a resolver at the end (lowest priority)."""
    r_none = FakeSyncResolver(None)
    chain = MentionResolverChain(resolvers=[r_none])  # type: ignore[arg-type]
    r_appended = FakeSyncResolver("appended")
    chain.append(r_appended)  # type: ignore[arg-type]
    assert chain.resolve("@ns:path.md") == "appended"


# ---------------------------------------------------------------------------
# Helpers for resolve_and_load tests
# ---------------------------------------------------------------------------


class FakeChain:
    """Fake chain that maps mentions to fixed content strings."""

    def __init__(self, mapping: dict[str, str | None]) -> None:
        self._mapping = mapping

    def resolve(self, mention: str) -> str | None:
        return self._mapping.get(mention)


class ExplodingChain:
    """Chain whose resolve() always raises RuntimeError."""

    def resolve(self, mention: str) -> str | None:
        raise RuntimeError("Resolver exploded!")


# ---------------------------------------------------------------------------
# Tests: resolve_and_load
# ---------------------------------------------------------------------------


def test_resolve_and_load_resolves_mentions() -> None:
    """Basic: resolves mentions in text and returns a ResolvedContent list."""
    chain = FakeChain({"@ns:a.md": "Content of A"})
    results = resolve_and_load("Load @ns:a.md here", chain)  # type: ignore[arg-type]
    assert len(results) == 1
    assert isinstance(results[0], ResolvedContent)
    assert results[0].key == "ns:a.md"
    assert results[0].content == "Content of A"


def test_resolve_and_load_recursive() -> None:
    """Resolved content that itself contains mentions is recursively loaded."""
    chain = FakeChain(
        {
            "@ns:a.md": "Load @ns:b.md here",
            "@ns:b.md": "Content of B",
        }
    )
    results = resolve_and_load("Load @ns:a.md here", chain)
    keys = [r.key for r in results]
    assert "ns:a.md" in keys
    assert "ns:b.md" in keys


def test_resolve_and_load_deduplicates_by_hash() -> None:
    """Two mentions resolving to identical content (same hash) produce only one result."""
    chain = FakeChain(
        {
            "@ns:a.md": "Same content",
            "@ns:b.md": "Same content",
        }
    )
    results = resolve_and_load("Load @ns:a.md and @ns:b.md here", chain)
    assert len(results) == 1


def test_resolve_and_load_depth_limit() -> None:
    """max_depth <= 0 returns an empty list immediately."""
    chain = FakeChain({"@ns:a.md": "Content of A"})
    results = resolve_and_load("Load @ns:a.md here", chain, max_depth=0)
    assert results == []


def test_resolve_and_load_shared_seen_hashes() -> None:
    """Passing an already-populated seen_hashes set prevents re-resolving content."""
    content = "Content of A"
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    seen: set[str] = {content_hash}
    chain = FakeChain({"@ns:a.md": content})
    results = resolve_and_load("Load @ns:a.md here", chain, seen_hashes=seen)
    assert results == []


def test_resolve_and_load_skips_unresolved() -> None:
    """Mentions for which the chain returns None are silently skipped."""
    chain = FakeChain(
        {
            "@ns:a.md": None,
            "@ns:b.md": "Content of B",
        }
    )
    results = resolve_and_load("Load @ns:a.md and @ns:b.md here", chain)
    assert len(results) == 1
    assert results[0].key == "ns:b.md"


def test_resolve_and_load_handles_resolver_exception() -> None:
    """Exceptions raised by chain.resolve() are caught; the mention is skipped."""
    results = resolve_and_load("Load @ns:a.md here", ExplodingChain())
    assert results == []
