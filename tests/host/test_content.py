"""Tests for content resolution and system prompt assembly."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from amplifier_ipc.host.content import assemble_system_prompt
from amplifier_ipc.host.config import HostSettings, SessionConfig
from amplifier_ipc.host.host import Host
from amplifier_ipc.host.lifecycle import ServiceProcess, shutdown_service
from amplifier_ipc.host.mentions import MentionResolverChain, NamespaceResolver
from amplifier_ipc.host.service_index import ServiceIndex
from amplifier_ipc.protocol.client import Client

_IPC_SRC = Path(__file__).parent.parent.parent / "src"


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


class FakeSyncResolver:
    """Test-only synchronous resolver that looks up mentions from a fixed mapping."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    def __call__(self, mention: str) -> str | None:
        key = mention.removeprefix("@")
        return self._mapping.get(key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_registry_and_services() -> tuple[ServiceIndex, dict]:
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

    registry = ServiceIndex()
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


async def test_assemble_system_prompt_with_resolver_chain() -> None:
    """resolver_chain resolves @mentions found in context/ files recursively."""
    # context/main.md contains an @mention to an agents/ file (excluded from auto-assembly)
    foundation_content: dict[str, str] = {
        "context/main.md": "main content referencing @foundation:agents/explorer.md",
        "agents/explorer.md": "explorer agent content",
    }

    registry = ServiceIndex()
    registry.register(
        "foundation",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": ["context/main.md"],
        },
    )
    services = {"foundation": FakeService(FakeClient(foundation_content))}

    # Sync resolver that maps the @mention to the explorer content
    resolver = FakeSyncResolver(
        {"foundation:agents/explorer.md": "explorer agent content"}
    )
    chain = MentionResolverChain([resolver])  # type: ignore[arg-type]

    result = await assemble_system_prompt(registry, services, resolver_chain=chain)

    # Direct context/ content is present
    assert "main content" in result
    # @mention in context/ file was resolved and appended
    assert "explorer agent content" in result


async def test_assemble_system_prompt_deduplicates() -> None:
    """Content resolved via @mention and also present as context/ file appears only once."""
    # context/main.md references @svc:context/shared.md via an @mention.
    # context/shared.md is also gathered as a context/ file.
    # The shared content must appear exactly once.
    svc_content: dict[str, str] = {
        "context/main.md": "main content mentioning @svc:context/shared.md",
        "context/shared.md": "shared content",
    }

    registry = ServiceIndex()
    registry.register(
        "svc",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": ["context/main.md", "context/shared.md"],
        },
    )
    services = {"svc": FakeService(FakeClient(svc_content))}

    # Resolver can resolve the @mention to "shared content"
    resolver = FakeSyncResolver({"svc:context/shared.md": "shared content"})
    chain = MentionResolverChain([resolver])  # type: ignore[arg-type]

    result = await assemble_system_prompt(registry, services, resolver_chain=chain)

    # "shared content" must appear exactly once even though it was reachable via two paths
    assert result.count("shared content") == 1


async def test_assemble_system_prompt_skips_failed_reads() -> None:
    """Failed content reads are logged and skipped; remaining content still assembles."""
    # Register two context/ paths but only provide content for one —
    # the missing path will raise KeyError inside FakeClient, triggering the
    # warning-and-skip branch in assemble_system_prompt.
    partial_content: dict[str, str] = {
        "context/philosophy.md": "philosophy content",
        # context/shared/common.md intentionally absent → FakeClient raises KeyError
    }

    registry = ServiceIndex()
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


# ---------------------------------------------------------------------------
# Real subprocess helpers
# ---------------------------------------------------------------------------


def _create_content_service_package(tmp_path: Path) -> Path:
    """Create a Python package with context/ and agents/ content files.

    Package layout::

        tmp_path/
          content_svc/
            __init__.py
            __main__.py           (Server("content_svc").run())
            context/
              philosophy.md       (# Philosophy\\nBe excellent.)
              guidelines.md       (# Guidelines\\nFollow the rules.)
            agents/
              explorer.md         (# Explorer Agent\\nExplore things.)

    Returns *tmp_path* (the parent of the package directory).
    """
    pkg = tmp_path / "content_svc"
    pkg.mkdir()

    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text(
        "from amplifier_ipc.protocol.server import Server\n"
        'Server("content_svc").run()\n'
    )

    context_dir = pkg / "context"
    context_dir.mkdir()
    (context_dir / "philosophy.md").write_text("# Philosophy\nBe excellent.")
    (context_dir / "guidelines.md").write_text("# Guidelines\nFollow the rules.")

    agents_dir = pkg / "agents"
    agents_dir.mkdir()
    (agents_dir / "explorer.md").write_text("# Explorer Agent\nExplore things.")

    return tmp_path


async def _spawn_content_service(pkg_parent: Path) -> ServiceProcess:
    """Spawn content_svc subprocess with the IPC src on PYTHONPATH."""
    existing = os.environ.get("PYTHONPATH", "")
    extra_paths = [str(pkg_parent), str(_IPC_SRC)]
    if existing:
        extra_paths.append(existing)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(extra_paths)

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "content_svc",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    assert process.stdout is not None
    assert process.stdin is not None
    client = Client(reader=process.stdout, writer=process.stdin)
    return ServiceProcess(name="content_svc", process=process, client=client)


# ---------------------------------------------------------------------------
# Integration tests: end-to-end with real subprocess
# ---------------------------------------------------------------------------


async def test_content_injection_end_to_end(tmp_path: Path) -> None:
    """Integration: _build_registry() + assemble_system_prompt() with a real subprocess.

    Spans the full content injection pipeline:

    1. A real service subprocess reports context/ and agents/ paths in its
       ``describe`` response (nested ``{"capabilities": {"content": {"paths": [...]}}}``)
    2. ``Host._build_registry()`` normalises the nested format and registers
       the content paths in the service index.
    3. ``assemble_system_prompt()`` fetches only ``context/`` files via
       ``content.read`` RPC—agents/ files are filtered out.
    4. Fetched content is wrapped in ``<context_file>`` XML blocks.
    """
    pkg_parent = _create_content_service_package(tmp_path)
    service = await _spawn_content_service(pkg_parent)

    config = SessionConfig(
        services=["content_svc"],
        orchestrator="",
        context_manager="",
        provider="",
    )
    host = Host(config=config, settings=HostSettings())
    host._services = {"content_svc": service}

    try:
        await host._build_registry()

        result = await assemble_system_prompt(host._registry, host._services)

        # context/ files must be present
        assert "Be excellent." in result
        assert "Follow the rules." in result

        # agents/ file must NOT be auto-included (context/ filter)
        assert "Explorer Agent" not in result

        # Content must be wrapped in XML context_file blocks
        assert "<context_file" in result
        assert "</context_file>" in result
    finally:
        await shutdown_service(service, timeout=5.0)


async def test_mention_resolution_end_to_end(tmp_path: Path) -> None:
    """Integration: NamespaceResolver routes @namespace:path to the correct service.

    Verifies that after ``_build_registry()`` populates the content registry,
    ``NamespaceResolver`` can:

    * Fetch a non-context/ file (agents/explorer.md) that is excluded from
      auto-assembly but accessible via explicit @mention.
    * Fetch a context/ file by explicit @mention too.

    This exercises the @namespace routing logic with a real subprocess.
    """
    pkg_parent = _create_content_service_package(tmp_path)
    service = await _spawn_content_service(pkg_parent)

    config = SessionConfig(
        services=["content_svc"],
        orchestrator="",
        context_manager="",
        provider="",
    )
    host = Host(config=config, settings=HostSettings())
    host._services = {"content_svc": service}

    try:
        await host._build_registry()

        ns_resolver = NamespaceResolver(host._registry, host._services)

        # agents/ file: excluded from auto-assembly but reachable via @mention
        agent_content = await ns_resolver("@content_svc:agents/explorer.md")
        assert agent_content == "# Explorer Agent\nExplore things."

        # context/ file: also reachable via explicit @mention
        ctx_content = await ns_resolver("@content_svc:context/philosophy.md")
        assert ctx_content == "# Philosophy\nBe excellent."
    finally:
        await shutdown_service(service, timeout=5.0)
