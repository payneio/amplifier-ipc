"""Tests for content resolution and system prompt assembly."""

from __future__ import annotations

import pytest

from amplifier_ipc_host.content import assemble_system_prompt, resolve_mention
from amplifier_ipc_host.registry import CapabilityRegistry


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClient:
    """Fake JSON-RPC client that serves content from an in-memory dict."""

    def __init__(self, content_map: dict[str, str]) -> None:
        self.content_map = content_map

    async def request(self, method: str, params: dict[str, str]) -> dict[str, str]:
        if method == "content.read":
            path = params["path"]
            if path not in self.content_map:
                raise KeyError(f"Unknown path: {path!r}")
            return {"content": self.content_map[path]}
        raise ValueError(f"Unsupported method: {method!r}")


class FakeService:
    """Minimal service stub with a fake client."""

    def __init__(self, client: FakeClient) -> None:
        self.client = client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_registry_and_services() -> tuple[CapabilityRegistry, dict]:
    """Create a registry and services dict with foundation and superpowers.

    foundation advertises: agents/explorer.md, context/shared/common.md
    superpowers advertises: context/philosophy.md
    """
    foundation_content: dict[str, str] = {
        "agents/explorer.md": "explorer agent content",
        "context/shared/common.md": "common shared content",
    }
    superpowers_content: dict[str, str] = {
        "context/philosophy.md": "philosophy content",
    }

    registry = CapabilityRegistry()
    registry.register(
        "foundation",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": ["agents/explorer.md", "context/shared/common.md"],
        },
    )
    registry.register(
        "superpowers",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": ["context/philosophy.md"],
        },
    )

    services = {
        "foundation": FakeService(FakeClient(foundation_content)),
        "superpowers": FakeService(FakeClient(superpowers_content)),
    }

    return registry, services


# ---------------------------------------------------------------------------
# Tests: resolve_mention
# ---------------------------------------------------------------------------


async def test_resolve_mention_simple() -> None:
    """Resolves a @namespace:path mention and returns the content."""
    registry, services = _build_registry_and_services()

    result = await resolve_mention("@foundation:agents/explorer.md", registry, services)

    assert result == "explorer agent content"


async def test_resolve_mention_unknown_service() -> None:
    """Raises ValueError when the namespace is not registered."""
    registry, services = _build_registry_and_services()

    with pytest.raises(ValueError, match="Unknown content namespace"):
        await resolve_mention("@unknown:some/path.md", registry, services)


async def test_resolve_mention_no_colon() -> None:
    """Raises ValueError when the mention contains no colon separator."""
    registry, services = _build_registry_and_services()

    with pytest.raises(ValueError, match="Invalid mention format"):
        await resolve_mention("@invalidformat", registry, services)


# ---------------------------------------------------------------------------
# Tests: assemble_system_prompt
# ---------------------------------------------------------------------------


async def test_assemble_system_prompt_gathers_context() -> None:
    """Gathers only context/ prefixed files from all registered services."""
    registry, services = _build_registry_and_services()

    result = await assemble_system_prompt(registry, services)

    # Should include context/ files from both services
    assert "common shared content" in result
    assert "philosophy content" in result

    # Should NOT include non-context/ files (agents/explorer.md)
    assert "explorer agent content" not in result


async def test_assemble_system_prompt_with_mentions() -> None:
    """Resolves extra @mentions and includes them in the output."""
    registry, services = _build_registry_and_services()

    result = await assemble_system_prompt(
        registry, services, mentions=["@foundation:agents/explorer.md"]
    )

    # Extra mention should be included
    assert "explorer agent content" in result
    # Context files still present
    assert "common shared content" in result
    assert "philosophy content" in result


async def test_assemble_system_prompt_deduplicates() -> None:
    """Same content appearing both as context file and as @mention is included only once."""
    registry, services = _build_registry_and_services()

    # @superpowers:context/philosophy.md is already gathered as a context/ file
    result = await assemble_system_prompt(
        registry, services, mentions=["@superpowers:context/philosophy.md"]
    )

    # philosophy content appears exactly once despite being listed twice
    assert result.count("philosophy content") == 1


async def test_assemble_system_prompt_skips_failed_reads() -> None:
    """Failed content reads are logged and skipped; remaining content still assembles."""
    # Register two context/ paths but only provide content for one —
    # the missing path will raise KeyError inside FakeClient, triggering the
    # warning-and-skip branch in assemble_system_prompt.
    partial_content: dict[str, str] = {
        "context/philosophy.md": "philosophy content",
        # context/shared/common.md intentionally absent → FakeClient raises KeyError
    }

    registry = CapabilityRegistry()
    registry.register(
        "foundation",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": ["context/shared/common.md", "context/philosophy.md"],
        },
    )

    services = {"foundation": FakeService(FakeClient(partial_content))}

    result = await assemble_system_prompt(registry, services)

    # Successful read is present
    assert "philosophy content" in result
    # Failed read is absent (gracefully skipped)
    assert "common shared content" not in result
