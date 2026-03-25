"""Tests for the mentions module — parsing, resolving, and loading @mentions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from amplifier_ipc.host.mentions import (
    NamespaceResolver,
    WorkingDirResolver,
    parse_mentions,
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


def test_working_dir_resolver_returns_none_for_missing_file(tmp_path: Path) -> None:
    """Returns None (with warning) when the resolved file does not exist."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    resolver = WorkingDirResolver(working_dir=tmp_path, home_dir=home_dir)
    result = resolver("@~/nonexistent.md")
    assert result is None
