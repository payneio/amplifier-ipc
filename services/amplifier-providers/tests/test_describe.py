"""Tests verifying describe reports all 8 providers with zero tools and zero hooks."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import amplifier_providers
from amplifier_ipc_protocol import ChatRequest, Message
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


def test_stub_provider_files_exist() -> None:
    """All 7 provider files must exist in the providers directory, including the full anthropic implementation."""
    pkg_dir = Path(amplifier_providers.__file__).parent  # type: ignore[arg-type]
    providers_dir = pkg_dir / "providers"

    stub_files = [
        "anthropic_provider.py",
        "openai_provider.py",
        "azure_openai_provider.py",
        "gemini_provider.py",
        "ollama_provider.py",
        "vllm_provider.py",
        "github_copilot_provider.py",
    ]
    for filename in stub_files:
        path = providers_dir / filename
        assert path.exists(), f"Stub file not found: {path}"


def test_stub_providers_raise_not_implemented() -> None:
    """All 5 stub providers must raise NotImplementedError on complete()."""
    stub_imports = [
        ("amplifier_providers.providers.azure_openai_provider", "AzureOpenAIProvider"),
        ("amplifier_providers.providers.gemini_provider", "GeminiProvider"),
        ("amplifier_providers.providers.ollama_provider", "OllamaProvider"),
        ("amplifier_providers.providers.vllm_provider", "VllmProvider"),
        (
            "amplifier_providers.providers.github_copilot_provider",
            "GitHubCopilotProvider",
        ),
    ]

    request = ChatRequest(messages=[Message(role="user", content="Hello")])

    for module_path, class_name in stub_imports:
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        instance = cls()

        try:
            asyncio.run(instance.complete(request))
            raise AssertionError(
                f"{class_name}.complete() did not raise NotImplementedError"
            )
        except NotImplementedError:
            pass  # Expected
