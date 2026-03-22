"""Tests verifying describe reports all 8 providers with zero tools and zero hooks."""

from __future__ import annotations

from amplifier_ipc_protocol.discovery import scan_package
from amplifier_ipc_protocol.server import Server

EXPECTED_PROVIDERS = {
    "mock",
    "anthropic",
    "openai",
    "azure_openai",
    "gemini",
    "ollama",
    "vllm",
    "github_copilot",
}


def test_scan_package_discovers_all_providers() -> None:
    """scan_package must discover all 8 providers."""
    components = scan_package("amplifier_providers")
    providers = components.get("provider", [])
    names = {getattr(p, "name", None) for p in providers}
    assert names == EXPECTED_PROVIDERS, (
        f"Expected providers {EXPECTED_PROVIDERS}, got {names}"
    )


async def test_describe_reports_all_8_providers() -> None:
    """Server.describe must report all 8 providers in capabilities."""
    server = Server("amplifier_providers")
    result = await server._handle_describe()

    assert "capabilities" in result
    capabilities = result["capabilities"]
    assert "providers" in capabilities

    provider_names = {p.get("name") for p in capabilities["providers"]}
    assert provider_names == EXPECTED_PROVIDERS, (
        f"Expected all 8 providers {EXPECTED_PROVIDERS}, got {provider_names}"
    )


async def test_describe_reports_zero_tools() -> None:
    """Server.describe must report zero tools."""
    server = Server("amplifier_providers")
    result = await server._handle_describe()

    tools = result["capabilities"]["tools"]
    assert tools == [], f"Expected zero tools, got {tools}"


async def test_describe_reports_zero_hooks() -> None:
    """Server.describe must report zero hooks."""
    server = Server("amplifier_providers")
    result = await server._handle_describe()

    hooks = result["capabilities"]["hooks"]
    assert hooks == [], f"Expected zero hooks, got {hooks}"
