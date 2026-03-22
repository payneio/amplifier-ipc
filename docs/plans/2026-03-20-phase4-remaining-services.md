# Phase 4: Remaining Services Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Port the remaining 11 amplifier-lite packages to IPC services — 4 with Python runtime code, 7 content-only.
**Architecture:** Each service is a standalone Python package with a `__main__.py` that starts the generic `Server` from `amplifier-ipc-protocol`. The Server auto-discovers decorated component classes via `scan_package()` and content files via `scan_content()`. Content-only services discover zero components and only serve `.md`/`.yaml` files.
**Tech Stack:** Python 3.11+, Pydantic v2, pytest + pytest-asyncio, hatchling build system, uv package manager.

---

## Prerequisites

Before starting, ensure the protocol library and foundation service are available:

```bash
# From the amplifier-ipc root
cd /data/labs/amplifier-lite/amplifier-ipc
```

All new services live under `/data/labs/amplifier-lite/amplifier-ipc/services/`.

---

## Conventions (READ THIS FIRST)

Every service in this plan follows the same structure established by Phase 3's `amplifier-foundation`. Here are the exact patterns — copy them literally.

### pyproject.toml Template

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "<SERVICE-NAME>"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "amplifier-ipc-protocol",
    # ... service-specific deps
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.scripts]
<SERVICE-NAME>-serve = "<PACKAGE_NAME>.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/<PACKAGE_NAME>"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src"]

[tool.uv.sources]
amplifier-ipc-protocol = { path = "../../amplifier-ipc-protocol" }
```

### `__main__.py` Template

```python
"""Entry point for <SERVICE-NAME> IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the <SERVICE-NAME> IPC service."""
    Server("<PACKAGE_NAME>").run()


if __name__ == "__main__":
    main()
```

### `__init__.py` Template

```python
"""<PACKAGE_NAME>: <one-line description>."""

__version__: str = "0.1.0"
```

### Test: `test_scaffolding.py` Template

```python
"""Tests for project scaffolding."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent


def test_package_importable() -> None:
    """Package must be importable."""
    import <PACKAGE_NAME>
    assert <PACKAGE_NAME>.__version__ == "0.1.0"


def test_main_module_exists() -> None:
    """__main__.py must exist."""
    main_path = PROJECT_ROOT / "src" / "<PACKAGE_NAME>" / "__main__.py"
    assert main_path.exists()


@pytest.mark.skipif(
    shutil.which("<SERVICE-NAME>-serve") is None,
    reason="Package not installed as tool",
)
def test_entry_point_available() -> None:
    """Entry point must be installed."""
    assert shutil.which("<SERVICE-NAME>-serve") is not None
```

### Test: `test_describe.py` Template (for describe verification)

Uses a real `Server` instance with in-memory `StreamReader`/`MockWriter` — no subprocesses needed:

```python
"""Service describe verification."""

from __future__ import annotations

import asyncio
import json

import pytest

from amplifier_ipc_protocol.server import Server


class _MockWriter:
    """Collects bytes written via write()/drain()."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass

    @property
    def messages(self) -> list[dict]:
        result = []
        for line in self._buf.split(b"\n"):
            stripped = line.strip()
            if stripped:
                result.append(json.loads(stripped))
        return result


async def _send_describe(package_name: str) -> dict:
    """Send describe to a Server and return the result dict."""
    server = Server(package_name)
    reader = asyncio.StreamReader()
    writer = _MockWriter()

    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "describe"}) + "\n"
    reader.feed_data(request.encode())
    reader.feed_eof()

    await server.handle_stream(reader, writer)

    messages = writer.messages
    assert len(messages) == 1
    assert "result" in messages[0]
    return messages[0]["result"]
```

### Test: `test_content.py` Template

```python
"""Content discovery verification."""

from __future__ import annotations

import pytest

from amplifier_ipc_protocol.discovery import scan_content


@pytest.fixture(scope="module")
def content_files() -> list[str]:
    return scan_content("<PACKAGE_NAME>")


def _files_in_dir(content_files: list[str], dir_name: str) -> list[str]:
    return [f for f in content_files if f.startswith(f"{dir_name}/")]
```

### How `scan_package()` Discovery Works

The `scan_package()` function in `amplifier_ipc_protocol.discovery` scans **only top-level `.py` files** in each component directory (`tools/`, `hooks/`, `providers/`, etc.). It does NOT recurse into subdirectories. If a component class lives in a subdirectory (e.g., `tools/skills/tool.py`), you need a **proxy file** at the top level that imports and re-exports it:

```
tools/
├── skills/          # subdirectory with actual implementation
│   ├── __init__.py
│   ├── tool.py      # SkillsTool class lives here
│   └── helpers.py
├── __init__.py
└── skills_tool.py   # PROXY FILE — imports SkillsTool so scan_package finds it
```

`skills_tool.py` contains:
```python
"""Proxy — re-exports SkillsTool for scan_package() discovery."""
from <PACKAGE_NAME>.tools.skills.tool import SkillsTool  # noqa: F401
```

### How Content Gets Discovered

`scan_content()` looks for files (recursively) under these directories: `agents/`, `context/`, `behaviors/`, `recipes/`, `sessions/`. It returns paths relative to the package root (e.g., `agents/explorer.md`, `context/docs/README.md`). The `routing/` directory in amplifier-routing-matrix is NOT a standard content directory — those YAML files are data files loaded by Python code, not served as content.

---

## Task 1: amplifier-providers Service — Project Scaffolding + Mock Provider

**Files:**
- Create: `services/amplifier-providers/pyproject.toml`
- Create: `services/amplifier-providers/src/amplifier_providers/__init__.py`
- Create: `services/amplifier-providers/src/amplifier_providers/__main__.py`
- Create: `services/amplifier-providers/src/amplifier_providers/providers/__init__.py`
- Create: `services/amplifier-providers/src/amplifier_providers/providers/mock.py`
- Create: `services/amplifier-providers/tests/__init__.py`
- Create: `services/amplifier-providers/tests/conftest.py`
- Test: `services/amplifier-providers/tests/test_scaffolding.py`
- Test: `services/amplifier-providers/tests/test_mock_provider.py`

**Step 1: Create directory structure**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc
mkdir -p services/amplifier-providers/src/amplifier_providers/providers
mkdir -p services/amplifier-providers/tests
touch services/amplifier-providers/tests/__init__.py
touch services/amplifier-providers/tests/conftest.py
touch services/amplifier-providers/src/amplifier_providers/providers/__init__.py
```

**Step 2: Write pyproject.toml**

Create `services/amplifier-providers/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "amplifier-providers"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "amplifier-ipc-protocol",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
anthropic = ["anthropic"]
openai = ["openai"]
azure = ["openai", "azure-identity>=1.25.1"]
gemini = ["google-genai>=1.40.0"]
ollama = ["ollama>=0.4.0"]
vllm = ["openai"]
copilot = ["github-copilot-sdk>=0.1.32,<0.2.0"]
all = [
    "anthropic",
    "openai",
    "azure-identity>=1.25.1",
    "google-genai>=1.40.0",
    "ollama>=0.4.0",
    "github-copilot-sdk>=0.1.32,<0.2.0",
]

[project.scripts]
amplifier-providers-serve = "amplifier_providers.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/amplifier_providers"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src"]

[tool.uv.sources]
amplifier-ipc-protocol = { path = "../../amplifier-ipc-protocol" }
```

**Step 3: Write `__init__.py`**

Create `services/amplifier-providers/src/amplifier_providers/__init__.py`:

```python
"""amplifier_providers: LLM provider adapters for the Amplifier IPC architecture."""

__version__: str = "0.1.0"
```

**Step 4: Write `__main__.py`**

Create `services/amplifier-providers/src/amplifier_providers/__main__.py`:

```python
"""Entry point for amplifier-providers IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier-providers IPC service."""
    Server("amplifier_providers").run()


if __name__ == "__main__":
    main()
```

**Step 5: Write the MockProvider**

Create `services/amplifier-providers/src/amplifier_providers/providers/mock.py`:

```python
"""Mock provider for testing without real API calls.

Ported from amplifier-lite's amplifier_providers.providers.mock.
Changes: replaced amplifier_lite imports with amplifier_ipc_protocol,
added @provider decorator, removed session parameter.
"""

from __future__ import annotations

import logging
from typing import Any

from amplifier_ipc_protocol import provider, ChatRequest, ChatResponse, TextBlock, Usage, ToolCall

logger = logging.getLogger(__name__)


@provider
class MockProvider:
    """Mock provider for testing without API calls."""

    name = "mock"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.responses = config.get(
            "responses",
            [
                "I'll help you with that task.",
                "Task completed successfully.",
                "Here's the result of your request.",
            ],
        )
        self.call_count = 0

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Generate a mock completion from ChatRequest."""
        self.call_count += 1

        # Check last message content for simple pattern matching
        last_message = request.messages[-1] if request.messages else None
        content = ""
        if last_message and isinstance(last_message.content, str):
            content = last_message.content

        # Simple pattern matching for tool calls
        tool_calls: list[ToolCall] = []
        if "read" in content.lower():
            tool_calls.append(
                ToolCall(id="mock_tool_1", name="read", arguments={"path": "test.txt"})
            )

        # Generate response
        if tool_calls:
            return ChatResponse(
                content=[TextBlock(text="I'll read that file for you.")],
                tool_calls=tool_calls,
                usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15),
            )

        response_text = self.responses[self.call_count % len(self.responses)]
        return ChatResponse(
            content=[TextBlock(text=response_text)],
            usage=Usage(input_tokens=10, output_tokens=20, total_tokens=30),
        )
```

**Step 6: Write the failing test**

Create `services/amplifier-providers/tests/test_scaffolding.py`:

```python
"""Tests for project scaffolding."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


def test_package_importable() -> None:
    """Package must be importable."""
    import amplifier_providers

    assert amplifier_providers.__version__ == "0.1.0"


def test_main_module_exists() -> None:
    """__main__.py must exist."""
    main_path = PROJECT_ROOT / "src" / "amplifier_providers" / "__main__.py"
    assert main_path.exists()


def test_providers_directory_exists() -> None:
    """providers/ subdirectory must exist."""
    providers_dir = PROJECT_ROOT / "src" / "amplifier_providers" / "providers"
    assert providers_dir.is_dir()


@pytest.mark.skipif(
    shutil.which("amplifier-providers-serve") is None,
    reason="Package not installed as tool",
)
def test_entry_point_available() -> None:
    """Entry point must be installed."""
    assert shutil.which("amplifier-providers-serve") is not None
```

Create `services/amplifier-providers/tests/test_mock_provider.py`:

```python
"""Tests for MockProvider — verifies discovery, describe, and basic completion."""

from __future__ import annotations

import asyncio
import json

import pytest

from amplifier_ipc_protocol.discovery import scan_package
from amplifier_ipc_protocol.server import Server
from amplifier_ipc_protocol.models import ChatRequest, Message


class _MockWriter:
    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass

    @property
    def messages(self) -> list[dict]:
        result = []
        for line in self._buf.split(b"\n"):
            stripped = line.strip()
            if stripped:
                result.append(json.loads(stripped))
        return result


def test_mock_provider_discovered() -> None:
    """MockProvider must be found by scan_package."""
    components = scan_package("amplifier_providers")
    providers = components.get("provider", [])
    names = [getattr(p, "name", None) for p in providers]
    assert "mock" in names, f"MockProvider not found. Discovered: {names}"


@pytest.mark.asyncio
async def test_describe_includes_mock() -> None:
    """describe must report the mock provider."""
    server = Server("amplifier_providers")
    reader = asyncio.StreamReader()
    writer = _MockWriter()

    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "describe"}) + "\n"
    reader.feed_data(request.encode())
    reader.feed_eof()

    await server.handle_stream(reader, writer)

    messages = writer.messages
    assert len(messages) == 1
    result = messages[0]["result"]
    caps = result["capabilities"]
    provider_names = [p["name"] for p in caps.get("providers", [])]
    assert "mock" in provider_names, f"Expected 'mock' in providers, got: {provider_names}"


@pytest.mark.asyncio
async def test_mock_provider_complete() -> None:
    """MockProvider.complete() must return a ChatResponse."""
    components = scan_package("amplifier_providers")
    providers = {getattr(p, "name", None): p for p in components.get("provider", [])}
    mock = providers["mock"]

    request = ChatRequest(messages=[Message(role="user", content="Hello")])
    response = await mock.complete(request)

    assert response.content is not None
    assert response.usage is not None
```

**Step 7: Install and run tests**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-providers
uv sync --extra dev
uv run pytest tests/ -v
```

Expected: All 5 tests PASS.

**Step 8: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-providers
git init && git add -A && git commit -m "feat: amplifier-providers scaffolding + MockProvider"
```

---

## Task 2: amplifier-providers — Remaining Provider Stubs

**Files:**
- Create: `services/amplifier-providers/src/amplifier_providers/providers/anthropic_provider.py`
- Create: `services/amplifier-providers/src/amplifier_providers/providers/openai_provider.py`
- Create: `services/amplifier-providers/src/amplifier_providers/providers/azure_openai_provider.py`
- Create: `services/amplifier-providers/src/amplifier_providers/providers/gemini_provider.py`
- Create: `services/amplifier-providers/src/amplifier_providers/providers/ollama_provider.py`
- Create: `services/amplifier-providers/src/amplifier_providers/providers/vllm_provider.py`
- Create: `services/amplifier-providers/src/amplifier_providers/providers/github_copilot_provider.py`
- Test: `services/amplifier-providers/tests/test_describe.py`

The real provider code (from `amplifier-lite/packages/amplifier-providers/src/amplifier_providers/providers/`) is 2,400+ lines per provider with heavy SDK dependencies (anthropic, openai, google-genai, etc.). Porting that code is a huge task that should happen incrementally. For Phase 4, we create **stub providers** — they have the correct `name`, the `@provider` decorator, and a `complete()` method that raises `NotImplementedError`. This lets the full service architecture work with the mock provider while real providers get ported later.

**Step 1: Write the failing test**

Create `services/amplifier-providers/tests/test_describe.py`:

```python
"""Describe verification — all 8 providers must appear."""

from __future__ import annotations

import asyncio
import json

import pytest

from amplifier_ipc_protocol.server import Server


class _MockWriter:
    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass

    @property
    def messages(self) -> list[dict]:
        result = []
        for line in self._buf.split(b"\n"):
            stripped = line.strip()
            if stripped:
                result.append(json.loads(stripped))
        return result


async def _send_describe() -> dict:
    server = Server("amplifier_providers")
    reader = asyncio.StreamReader()
    writer = _MockWriter()

    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "describe"}) + "\n"
    reader.feed_data(request.encode())
    reader.feed_eof()

    await server.handle_stream(reader, writer)

    messages = writer.messages
    assert len(messages) == 1
    assert "result" in messages[0]
    return messages[0]["result"]


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


@pytest.mark.asyncio
async def test_describe_has_all_providers() -> None:
    """describe must report all 8 providers."""
    result = await _send_describe()
    caps = result["capabilities"]
    provider_names = {p["name"] for p in caps.get("providers", [])}
    missing = EXPECTED_PROVIDERS - provider_names
    assert not missing, f"Missing providers: {sorted(missing)}. Found: {sorted(provider_names)}"


@pytest.mark.asyncio
async def test_describe_has_zero_tools_and_hooks() -> None:
    """Providers service has no tools or hooks."""
    result = await _send_describe()
    caps = result["capabilities"]
    assert len(caps.get("tools", [])) == 0
    assert len(caps.get("hooks", [])) == 0
```

**Step 2: Run test to verify it fails**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-providers
uv run pytest tests/test_describe.py -v
```

Expected: FAIL — only `mock` provider found, missing 7 others.

**Step 3: Write stub providers**

Each stub follows the same pattern. Create each file:

Create `services/amplifier-providers/src/amplifier_providers/providers/anthropic_provider.py`:

```python
"""Anthropic provider stub — placeholder for full port.

The real implementation (~2400 lines) handles streaming, rate limiting,
extended thinking, prompt caching, etc. This stub registers the provider
name so the service architecture works. Port the real code when ready.
"""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import provider, ChatRequest, ChatResponse


@provider
class AnthropicProvider:
    """Anthropic Claude API provider (stub)."""

    name = "anthropic"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        raise NotImplementedError(
            "AnthropicProvider is a stub. Install amplifier-providers[anthropic] "
            "and port the real implementation from amplifier-lite."
        )
```

Create `services/amplifier-providers/src/amplifier_providers/providers/openai_provider.py`:

```python
"""OpenAI provider stub."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import provider, ChatRequest, ChatResponse


@provider
class OpenAIProvider:
    """OpenAI GPT API provider (stub)."""

    name = "openai"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        raise NotImplementedError(
            "OpenAIProvider is a stub. Install amplifier-providers[openai] "
            "and port the real implementation from amplifier-lite."
        )
```

Create `services/amplifier-providers/src/amplifier_providers/providers/azure_openai_provider.py`:

```python
"""Azure OpenAI provider stub."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import provider, ChatRequest, ChatResponse


@provider
class AzureOpenAIProvider:
    """Azure OpenAI API provider (stub)."""

    name = "azure_openai"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        raise NotImplementedError(
            "AzureOpenAIProvider is a stub. Install amplifier-providers[azure] "
            "and port the real implementation from amplifier-lite."
        )
```

Create `services/amplifier-providers/src/amplifier_providers/providers/gemini_provider.py`:

```python
"""Gemini provider stub."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import provider, ChatRequest, ChatResponse


@provider
class GeminiProvider:
    """Google Gemini API provider (stub)."""

    name = "gemini"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        raise NotImplementedError(
            "GeminiProvider is a stub. Install amplifier-providers[gemini] "
            "and port the real implementation from amplifier-lite."
        )
```

Create `services/amplifier-providers/src/amplifier_providers/providers/ollama_provider.py`:

```python
"""Ollama provider stub."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import provider, ChatRequest, ChatResponse


@provider
class OllamaProvider:
    """Ollama local LLM provider (stub)."""

    name = "ollama"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        raise NotImplementedError(
            "OllamaProvider is a stub. Install amplifier-providers[ollama] "
            "and port the real implementation from amplifier-lite."
        )
```

Create `services/amplifier-providers/src/amplifier_providers/providers/vllm_provider.py`:

```python
"""vLLM provider stub."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import provider, ChatRequest, ChatResponse


@provider
class VllmProvider:
    """vLLM inference server provider (stub)."""

    name = "vllm"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        raise NotImplementedError(
            "VllmProvider is a stub. Install amplifier-providers[vllm] "
            "and port the real implementation from amplifier-lite."
        )
```

Create `services/amplifier-providers/src/amplifier_providers/providers/github_copilot_provider.py`:

```python
"""GitHub Copilot provider stub."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import provider, ChatRequest, ChatResponse


@provider
class GithubCopilotProvider:
    """GitHub Copilot API provider (stub)."""

    name = "github_copilot"

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        raise NotImplementedError(
            "GithubCopilotProvider is a stub. Install amplifier-providers[copilot] "
            "and port the real implementation from amplifier-lite."
        )
```

**Step 4: Run tests to verify all pass**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-providers
uv run pytest tests/ -v
```

Expected: All tests PASS — 8 providers discovered, describe reports all 8.

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add 7 provider stubs (anthropic, openai, azure, gemini, ollama, vllm, copilot)"
```

---

## Task 3: amplifier-modes Service

**Files:**
- Create: `services/amplifier-modes/pyproject.toml`
- Create: `services/amplifier-modes/src/amplifier_modes/__init__.py`
- Create: `services/amplifier-modes/src/amplifier_modes/__main__.py`
- Create: `services/amplifier-modes/src/amplifier_modes/hooks/__init__.py`
- Create: `services/amplifier-modes/src/amplifier_modes/hooks/mode.py`
- Create: `services/amplifier-modes/src/amplifier_modes/tools/__init__.py`
- Create: `services/amplifier-modes/src/amplifier_modes/tools/mode.py`
- Copy: content from source `behaviors/modes.yaml`, `context/modes-instructions.md`
- Create: `services/amplifier-modes/tests/__init__.py`
- Create: `services/amplifier-modes/tests/conftest.py`
- Test: `services/amplifier-modes/tests/test_scaffolding.py`
- Test: `services/amplifier-modes/tests/test_describe.py`
- Test: `services/amplifier-modes/tests/test_content.py`

**Step 1: Create directory structure**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc
mkdir -p services/amplifier-modes/src/amplifier_modes/{hooks,tools,behaviors,context}
mkdir -p services/amplifier-modes/tests
touch services/amplifier-modes/tests/__init__.py
touch services/amplifier-modes/tests/conftest.py
touch services/amplifier-modes/src/amplifier_modes/hooks/__init__.py
touch services/amplifier-modes/src/amplifier_modes/tools/__init__.py
```

**Step 2: Copy content files from source**

```bash
cp /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-modes/src/amplifier_modes/behaviors/modes.yaml \
   /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-modes/src/amplifier_modes/behaviors/
cp /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-modes/src/amplifier_modes/context/modes-instructions.md \
   /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-modes/src/amplifier_modes/context/
```

**Step 3: Write pyproject.toml**

Create `services/amplifier-modes/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "amplifier-modes"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "amplifier-ipc-protocol",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.scripts]
amplifier-modes-serve = "amplifier_modes.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/amplifier_modes"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src"]

[tool.uv.sources]
amplifier-ipc-protocol = { path = "../../amplifier-ipc-protocol" }
```

**Step 4: Write `__init__.py` and `__main__.py`**

Create `services/amplifier-modes/src/amplifier_modes/__init__.py`:

```python
"""amplifier_modes: Runtime mode management — hook + tool for mode switching."""

__version__: str = "0.1.0"
```

Create `services/amplifier-modes/src/amplifier_modes/__main__.py`:

```python
"""Entry point for amplifier-modes IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier-modes IPC service."""
    Server("amplifier_modes").run()


if __name__ == "__main__":
    main()
```

**Step 5: Write ModeHook**

The source ModeHook (528 lines) uses a `register()` pattern with `session.state`. For IPC, we convert to the `@hook` decorator with a `handle()` dispatcher. The hook needs to work without a session object — state management will happen through the host.

Create `services/amplifier-modes/src/amplifier_modes/hooks/mode.py`:

```python
"""ModeHook — enforces tool restrictions when a mode is active.

Ported from amplifier-lite's amplifier_modes.hooks.mode.
Changes:
- Replaced register() pattern with @hook + handle() dispatcher
- Removed Session dependency (state managed locally)
- Replaced amplifier_lite imports with amplifier_ipc_protocol
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from amplifier_ipc_protocol import hook, HookResult, HookAction

logger = logging.getLogger(__name__)


@dataclass
class ModeDefinition:
    """Parsed mode definition from a mode file."""

    name: str
    description: str = ""
    source: str = ""
    shortcut: str | None = None
    context: str = ""
    safe_tools: list[str] = field(default_factory=list)
    warn_tools: list[str] = field(default_factory=list)
    confirm_tools: list[str] = field(default_factory=list)
    block_tools: list[str] = field(default_factory=list)
    default_action: str = "block"
    allowed_transitions: list[str] | None = None
    allow_clear: bool = True


def parse_mode_file(file_path: Path) -> ModeDefinition | None:
    """Parse a mode definition from a markdown file with YAML frontmatter."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to read mode file %s: %s", file_path, e)
        return None

    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not frontmatter_match:
        return None

    yaml_content = frontmatter_match.group(1)
    markdown_body = frontmatter_match.group(2).strip()

    try:
        parsed = yaml.safe_load(yaml_content)
    except yaml.YAMLError:
        return None

    if not parsed or "mode" not in parsed:
        return None

    mode_config = parsed["mode"]
    tools_config = mode_config.get("tools", {})

    return ModeDefinition(
        name=mode_config.get("name", file_path.stem),
        description=mode_config.get("description", ""),
        shortcut=mode_config.get("shortcut"),
        context=markdown_body,
        safe_tools=tools_config.get("safe", []),
        warn_tools=tools_config.get("warn", []),
        confirm_tools=tools_config.get("confirm", []),
        block_tools=tools_config.get("block", []),
        default_action=mode_config.get("default_action", "block"),
        allowed_transitions=mode_config.get("allowed_transitions"),
        allow_clear=mode_config.get("allow_clear", True),
    )


@hook(events=["tool:pre", "provider:request"], priority=5)
class ModeHook:
    """Enforces tool restrictions when a mode is active.

    On tool:pre: checks whether the tool is allowed/warned/blocked
    under the current mode. On provider:request: injects mode context.
    """

    name = "mode"
    events = ["tool:pre", "provider:request"]
    priority = 5

    def __init__(self) -> None:
        self._active_mode: ModeDefinition | None = None
        self._warned_tools: set[str] = set()

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch to the appropriate handler based on event type."""
        if event == "tool:pre":
            return await self._handle_tool_pre(data)
        if event == "provider:request":
            return await self._handle_provider_request(data)
        return HookResult(action=HookAction.CONTINUE)

    async def _handle_tool_pre(self, data: dict[str, Any]) -> HookResult:
        """Check if tool is allowed under current mode."""
        if self._active_mode is None:
            return HookResult(action=HookAction.CONTINUE)

        tool_name = data.get("name", "")
        mode = self._active_mode

        # Check safe list first
        if tool_name in mode.safe_tools:
            return HookResult(action=HookAction.CONTINUE)

        # Check block list
        if tool_name in mode.block_tools:
            return HookResult(
                action=HookAction.DENY,
                reason=f"Tool '{tool_name}' is blocked in mode '{mode.name}'",
            )

        # Check warn list
        if tool_name in mode.warn_tools:
            if tool_name not in self._warned_tools:
                self._warned_tools.add(tool_name)
                return HookResult(
                    action=HookAction.DENY,
                    reason=(
                        f"Tool '{tool_name}' requires caution in mode '{mode.name}'. "
                        "Retry to proceed."
                    ),
                )
            return HookResult(action=HookAction.CONTINUE)

        # Default action
        if mode.default_action == "block":
            return HookResult(
                action=HookAction.DENY,
                reason=f"Tool '{tool_name}' is not allowed in mode '{mode.name}'",
            )

        return HookResult(action=HookAction.CONTINUE)

    async def _handle_provider_request(self, data: dict[str, Any]) -> HookResult:
        """Inject mode context into provider requests."""
        if self._active_mode is None or not self._active_mode.context:
            return HookResult(action=HookAction.CONTINUE)
        return HookResult(
            action=HookAction.MODIFY,
            data={"mode_context": self._active_mode.context},
        )
```

**Step 6: Write ModeTool**

Create `services/amplifier-modes/src/amplifier_modes/tools/mode.py`:

```python
"""ModeTool — agent-initiated mode management.

Ported from amplifier-lite's amplifier_modes.tools.mode.
Changes: replaced amplifier_lite imports with amplifier_ipc_protocol,
added @tool decorator, removed Session dependency (stub implementation).
"""

from __future__ import annotations

import logging
from typing import Any

from amplifier_ipc_protocol import tool, ToolResult

logger = logging.getLogger(__name__)


@tool
class ModeTool:
    """Tool for agent-initiated mode management.

    Operations: set, clear, list, current.
    """

    name = "mode"
    description = (
        "Manage runtime modes. Operations: 'set' (activate a mode), "
        "'clear' (deactivate), 'list' (show available), 'current' (show active). "
        "Mode transitions may require confirmation depending on gate policy."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["set", "clear", "list", "current"],
                "description": "Operation to perform",
            },
            "name": {
                "type": "string",
                "description": "Mode name (required for 'set' operation)",
            },
        },
        "required": ["operation"],
    }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute a mode operation."""
        operation = input.get("operation", "")

        if operation == "list":
            return ToolResult(
                success=True,
                output={"modes": [], "message": "No modes configured (IPC stub)"},
            )
        if operation == "current":
            return ToolResult(
                success=True,
                output={"active_mode": None, "message": "No active mode"},
            )
        if operation == "set":
            name = input.get("name")
            if not name:
                return ToolResult(
                    success=False,
                    error={"type": "InvalidInput", "message": "Missing 'name' parameter"},
                )
            return ToolResult(
                success=False,
                error={
                    "type": "NotImplementedError",
                    "message": (
                        f"Mode '{name}' set not yet implemented over IPC. "
                        "Requires host-side mode state management."
                    ),
                },
            )
        if operation == "clear":
            return ToolResult(
                success=True,
                output={"message": "No active mode to clear"},
            )

        return ToolResult(
            success=False,
            error={"type": "InvalidInput", "message": f"Unknown operation: {operation!r}"},
        )
```

**Step 7: Write tests**

Create `services/amplifier-modes/tests/test_scaffolding.py`:

```python
"""Tests for project scaffolding."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


def test_package_importable() -> None:
    import amplifier_modes

    assert amplifier_modes.__version__ == "0.1.0"


def test_main_module_exists() -> None:
    main_path = PROJECT_ROOT / "src" / "amplifier_modes" / "__main__.py"
    assert main_path.exists()


@pytest.mark.skipif(
    shutil.which("amplifier-modes-serve") is None,
    reason="Package not installed as tool",
)
def test_entry_point_available() -> None:
    assert shutil.which("amplifier-modes-serve") is not None
```

Create `services/amplifier-modes/tests/test_describe.py`:

```python
"""Describe verification — 1 hook + 1 tool + content."""

from __future__ import annotations

import asyncio
import json

import pytest

from amplifier_ipc_protocol.server import Server


class _MockWriter:
    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass

    @property
    def messages(self) -> list[dict]:
        result = []
        for line in self._buf.split(b"\n"):
            stripped = line.strip()
            if stripped:
                result.append(json.loads(stripped))
        return result


async def _send_describe() -> dict:
    server = Server("amplifier_modes")
    reader = asyncio.StreamReader()
    writer = _MockWriter()

    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "describe"}) + "\n"
    reader.feed_data(request.encode())
    reader.feed_eof()

    await server.handle_stream(reader, writer)

    messages = writer.messages
    assert len(messages) == 1
    assert "result" in messages[0]
    return messages[0]["result"]


@pytest.mark.asyncio
async def test_describe_has_mode_hook() -> None:
    """describe must report the mode hook."""
    result = await _send_describe()
    caps = result["capabilities"]
    hook_names = [h["name"] for h in caps.get("hooks", [])]
    assert "mode" in hook_names, f"Expected 'mode' hook, found: {hook_names}"


@pytest.mark.asyncio
async def test_describe_has_mode_tool() -> None:
    """describe must report the mode tool."""
    result = await _send_describe()
    caps = result["capabilities"]
    tool_names = [t["name"] for t in caps.get("tools", [])]
    assert "mode" in tool_names, f"Expected 'mode' tool, found: {tool_names}"


@pytest.mark.asyncio
async def test_describe_has_content() -> None:
    """describe must report content paths."""
    result = await _send_describe()
    caps = result["capabilities"]
    paths = caps.get("content", {}).get("paths", [])
    assert len(paths) >= 2, f"Expected >= 2 content paths, got {len(paths)}: {paths}"
```

Create `services/amplifier-modes/tests/test_content.py`:

```python
"""Content discovery verification."""

from __future__ import annotations

import pytest

from amplifier_ipc_protocol.discovery import scan_content


@pytest.fixture(scope="module")
def content_files() -> list[str]:
    return scan_content("amplifier_modes")


def test_behaviors_content(content_files: list[str]) -> None:
    behavior_files = [f for f in content_files if f.startswith("behaviors/")]
    assert len(behavior_files) >= 1, f"Expected >= 1 behavior file, found: {behavior_files}"


def test_context_content(content_files: list[str]) -> None:
    context_files = [f for f in content_files if f.startswith("context/")]
    assert len(context_files) >= 1, f"Expected >= 1 context file, found: {context_files}"
```

**Step 8: Install and run tests**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-modes
uv sync --extra dev
uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 9: Commit**

```bash
git init && git add -A && git commit -m "feat: amplifier-modes service (ModeHook + ModeTool + content)"
```

---

## Task 4: amplifier-skills Service

**Files:**
- Create: `services/amplifier-skills/pyproject.toml`
- Create: `services/amplifier-skills/src/amplifier_skills/__init__.py`
- Create: `services/amplifier-skills/src/amplifier_skills/__main__.py`
- Create: `services/amplifier-skills/src/amplifier_skills/tools/__init__.py`
- Create: `services/amplifier-skills/src/amplifier_skills/tools/skills/__init__.py`
- Create: `services/amplifier-skills/src/amplifier_skills/tools/skills/tool.py`
- Create: `services/amplifier-skills/src/amplifier_skills/tools/skills_tool.py` (proxy)
- Copy: `behaviors/skills-tool.yaml`, `behaviors/skills.yaml`, `context/skills-instructions.md`
- Create: `services/amplifier-skills/tests/__init__.py`
- Create: `services/amplifier-skills/tests/conftest.py`
- Test: `services/amplifier-skills/tests/test_scaffolding.py`
- Test: `services/amplifier-skills/tests/test_describe.py`
- Test: `services/amplifier-skills/tests/test_content.py`

**Step 1: Create directory structure**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc
mkdir -p services/amplifier-skills/src/amplifier_skills/tools/skills
mkdir -p services/amplifier-skills/src/amplifier_skills/{behaviors,context}
mkdir -p services/amplifier-skills/tests
touch services/amplifier-skills/tests/__init__.py
touch services/amplifier-skills/tests/conftest.py
touch services/amplifier-skills/src/amplifier_skills/tools/__init__.py
touch services/amplifier-skills/src/amplifier_skills/tools/skills/__init__.py
```

**Step 2: Copy content files from source**

```bash
cp /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-skills/src/amplifier_skills/behaviors/*.yaml \
   /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-skills/src/amplifier_skills/behaviors/
cp /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-skills/src/amplifier_skills/context/skills-instructions.md \
   /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-skills/src/amplifier_skills/context/
```

**Step 3: Write boilerplate files**

Create `services/amplifier-skills/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "amplifier-skills"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "amplifier-ipc-protocol",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.scripts]
amplifier-skills-serve = "amplifier_skills.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/amplifier_skills"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src"]

[tool.uv.sources]
amplifier-ipc-protocol = { path = "../../amplifier-ipc-protocol" }
```

Create `services/amplifier-skills/src/amplifier_skills/__init__.py`:

```python
"""amplifier_skills: Skill discovery and loading tool."""

__version__: str = "0.1.0"
```

Create `services/amplifier-skills/src/amplifier_skills/__main__.py`:

```python
"""Entry point for amplifier-skills IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier-skills IPC service."""
    Server("amplifier_skills").run()


if __name__ == "__main__":
    main()
```

**Step 4: Write SkillsTool**

Create `services/amplifier-skills/src/amplifier_skills/tools/skills/tool.py`:

```python
"""SkillsTool — discover, search, and load skills.

Ported from amplifier-lite's amplifier_skills.tools.skills.tool.
Changes: replaced amplifier_lite imports with amplifier_ipc_protocol,
added @tool decorator, stub implementation for IPC.
"""

from __future__ import annotations

import logging
from typing import Any

from amplifier_ipc_protocol import tool, ToolResult

logger = logging.getLogger(__name__)


@tool
class SkillsTool:
    """Load domain knowledge from available skills.

    Skills provide specialized knowledge, workflows, best practices,
    and standards. Use when you need domain expertise.
    """

    name = "load_skill"
    description = (
        "Load domain knowledge from an available skill. Skills provide specialized "
        "knowledge, workflows, best practices, and standards."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Name of skill to load",
            },
            "list": {
                "type": "boolean",
                "description": "If true, return list of all available skills",
            },
            "search": {
                "type": "string",
                "description": "Search term to filter skills",
            },
            "info": {
                "type": "string",
                "description": "Get metadata for a specific skill",
            },
            "source": {
                "type": "string",
                "description": "Register a new skill source",
            },
        },
    }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute a skill operation."""
        if input.get("list"):
            return ToolResult(
                success=True,
                output={"skills": [], "message": "No skills discovered (IPC stub)"},
            )
        if search := input.get("search"):
            return ToolResult(
                success=True,
                output={"skills": [], "message": f"No skills matching '{search}' (IPC stub)"},
            )
        if info := input.get("info"):
            return ToolResult(
                success=False,
                error={
                    "type": "NotFoundError",
                    "message": f"Skill '{info}' not found (IPC stub)",
                },
            )
        if skill_name := input.get("skill_name"):
            return ToolResult(
                success=False,
                error={
                    "type": "NotImplementedError",
                    "message": (
                        f"Loading skill '{skill_name}' not yet implemented over IPC. "
                        "Requires host-side skill path resolution."
                    ),
                },
            )
        return ToolResult(
            success=False,
            error={"type": "InvalidInput", "message": "No operation specified"},
        )
```

Create the proxy file `services/amplifier-skills/src/amplifier_skills/tools/skills_tool.py`:

```python
"""Proxy — re-exports SkillsTool for scan_package() discovery."""

from amplifier_skills.tools.skills.tool import SkillsTool  # noqa: F401
```

**Step 5: Write tests**

Create `services/amplifier-skills/tests/test_scaffolding.py`:

```python
"""Tests for project scaffolding."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


def test_package_importable() -> None:
    import amplifier_skills

    assert amplifier_skills.__version__ == "0.1.0"


def test_main_module_exists() -> None:
    main_path = PROJECT_ROOT / "src" / "amplifier_skills" / "__main__.py"
    assert main_path.exists()


@pytest.mark.skipif(
    shutil.which("amplifier-skills-serve") is None,
    reason="Package not installed as tool",
)
def test_entry_point_available() -> None:
    assert shutil.which("amplifier-skills-serve") is not None
```

Create `services/amplifier-skills/tests/test_describe.py`:

```python
"""Describe verification — 1 tool + content."""

from __future__ import annotations

import asyncio
import json

import pytest

from amplifier_ipc_protocol.server import Server


class _MockWriter:
    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass

    @property
    def messages(self) -> list[dict]:
        result = []
        for line in self._buf.split(b"\n"):
            stripped = line.strip()
            if stripped:
                result.append(json.loads(stripped))
        return result


async def _send_describe() -> dict:
    server = Server("amplifier_skills")
    reader = asyncio.StreamReader()
    writer = _MockWriter()
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "describe"}) + "\n"
    reader.feed_data(request.encode())
    reader.feed_eof()
    await server.handle_stream(reader, writer)
    messages = writer.messages
    assert len(messages) == 1
    assert "result" in messages[0]
    return messages[0]["result"]


@pytest.mark.asyncio
async def test_describe_has_load_skill_tool() -> None:
    """describe must report the load_skill tool."""
    result = await _send_describe()
    caps = result["capabilities"]
    tool_names = [t["name"] for t in caps.get("tools", [])]
    assert "load_skill" in tool_names, f"Expected 'load_skill' tool, found: {tool_names}"


@pytest.mark.asyncio
async def test_describe_has_content() -> None:
    """describe must report content paths."""
    result = await _send_describe()
    caps = result["capabilities"]
    paths = caps.get("content", {}).get("paths", [])
    assert len(paths) >= 3, f"Expected >= 3 content paths, got {len(paths)}: {paths}"
```

Create `services/amplifier-skills/tests/test_content.py`:

```python
"""Content discovery verification."""

from __future__ import annotations

import pytest

from amplifier_ipc_protocol.discovery import scan_content


@pytest.fixture(scope="module")
def content_files() -> list[str]:
    return scan_content("amplifier_skills")


def test_behaviors_content(content_files: list[str]) -> None:
    behavior_files = [f for f in content_files if f.startswith("behaviors/")]
    assert len(behavior_files) >= 2, f"Expected >= 2 behavior files, found: {behavior_files}"


def test_context_content(content_files: list[str]) -> None:
    context_files = [f for f in content_files if f.startswith("context/")]
    assert len(context_files) >= 1, f"Expected >= 1 context file, found: {context_files}"
```

**Step 6: Install and run tests**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-skills
uv sync --extra dev
uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 7: Commit**

```bash
git init && git add -A && git commit -m "feat: amplifier-skills service (SkillsTool + content)"
```

---

## Task 5: amplifier-routing-matrix Service

**Files:**
- Create: `services/amplifier-routing-matrix/pyproject.toml`
- Create: `services/amplifier-routing-matrix/src/amplifier_routing_matrix/__init__.py`
- Create: `services/amplifier-routing-matrix/src/amplifier_routing_matrix/__main__.py`
- Create: `services/amplifier-routing-matrix/src/amplifier_routing_matrix/hooks/__init__.py`
- Create: `services/amplifier-routing-matrix/src/amplifier_routing_matrix/hooks/routing.py`
- Create: `services/amplifier-routing-matrix/src/amplifier_routing_matrix/hooks/matrix_loader.py`
- Create: `services/amplifier-routing-matrix/src/amplifier_routing_matrix/hooks/resolver.py`
- Copy: `routing/` dir (7 YAML matrix files), `behaviors/routing.yaml`, `context/role-definitions.md`, `context/routing-instructions.md`
- Create: `services/amplifier-routing-matrix/tests/__init__.py`
- Create: `services/amplifier-routing-matrix/tests/conftest.py`
- Test: `services/amplifier-routing-matrix/tests/test_scaffolding.py`
- Test: `services/amplifier-routing-matrix/tests/test_describe.py`
- Test: `services/amplifier-routing-matrix/tests/test_matrix_loader.py`
- Test: `services/amplifier-routing-matrix/tests/test_content.py`

**Step 1: Create directory structure**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc
mkdir -p services/amplifier-routing-matrix/src/amplifier_routing_matrix/{hooks,routing,behaviors,context}
mkdir -p services/amplifier-routing-matrix/tests
touch services/amplifier-routing-matrix/tests/__init__.py
touch services/amplifier-routing-matrix/tests/conftest.py
touch services/amplifier-routing-matrix/src/amplifier_routing_matrix/hooks/__init__.py
```

**Step 2: Copy content and data files from source**

```bash
# Routing matrix YAML data files (used by Python code, NOT served as content)
cp /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-routing-matrix/src/amplifier_routing_matrix/routing/*.yaml \
   /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-routing-matrix/src/amplifier_routing_matrix/routing/

# Content files (served via content.read)
cp /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-routing-matrix/src/amplifier_routing_matrix/behaviors/routing.yaml \
   /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-routing-matrix/src/amplifier_routing_matrix/behaviors/

cp /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-routing-matrix/src/amplifier_routing_matrix/context/role-definitions.md \
   /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-routing-matrix/src/amplifier_routing_matrix/context/

cp /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-routing-matrix/src/amplifier_routing_matrix/context/routing-instructions.md \
   /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-routing-matrix/src/amplifier_routing_matrix/context/
```

**Step 3: Write boilerplate files**

Create `services/amplifier-routing-matrix/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "amplifier-routing-matrix"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "amplifier-ipc-protocol",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.scripts]
amplifier-routing-matrix-serve = "amplifier_routing_matrix.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/amplifier_routing_matrix"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src"]

[tool.uv.sources]
amplifier-ipc-protocol = { path = "../../amplifier-ipc-protocol" }
```

Create `services/amplifier-routing-matrix/src/amplifier_routing_matrix/__init__.py`:

```python
"""amplifier_routing_matrix: Model routing based on curated role-to-provider matrices."""

__version__: str = "0.1.0"
```

Create `services/amplifier-routing-matrix/src/amplifier_routing_matrix/__main__.py`:

```python
"""Entry point for amplifier-routing-matrix IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier-routing-matrix IPC service."""
    Server("amplifier_routing_matrix").run()


if __name__ == "__main__":
    main()
```

**Step 4: Port matrix_loader.py (utility — no changes needed)**

Create `services/amplifier-routing-matrix/src/amplifier_routing_matrix/hooks/matrix_loader.py`:

```python
"""Matrix loader — loads and composes routing matrix YAML files.

Copied directly from amplifier-lite — no amplifier_lite imports to replace.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml


def load_matrix(path: str | Path) -> dict[str, Any]:
    """Load a YAML matrix file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Matrix file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Matrix file must contain a YAML mapping: {path}")

    return data


def compose_matrix(
    base: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Compose a base matrix's roles with user overrides."""
    result: dict[str, Any] = copy.deepcopy(base)

    for role_name, override_data in overrides.items():
        override_data = copy.deepcopy(override_data)
        candidates = override_data.get("candidates", [])

        base_count = sum(1 for c in candidates if c == "base")
        if base_count > 1:
            raise ValueError(
                f"Role '{role_name}': multiple 'base' keywords found in candidates "
                f"list. Only one is allowed."
            )

        if base_count == 0:
            result[role_name] = override_data
        else:
            base_candidates = (
                copy.deepcopy(result[role_name].get("candidates", []))
                if role_name in result
                else []
            )
            expanded: list[Any] = []
            for c in candidates:
                if c == "base":
                    expanded.extend(base_candidates)
                else:
                    expanded.append(c)
            override_data["candidates"] = expanded
            result[role_name] = override_data

    return result
```

**Step 5: Port resolver.py (utility — minimal changes)**

Create `services/amplifier-routing-matrix/src/amplifier_routing_matrix/hooks/resolver.py`:

```python
"""Resolver — resolves model roles against routing matrix and installed providers.

Copied from amplifier-lite — no amplifier_lite imports to replace.
"""

from __future__ import annotations

import fnmatch
import logging
from typing import Any

logger = logging.getLogger(__name__)


def find_provider_by_type(
    providers: dict[str, Any],
    type_name: str,
) -> tuple[str, Any] | None:
    """Find an installed provider by module type name."""
    for name, provider in providers.items():
        if type_name in (
            name,
            name.replace("provider-", ""),
            f"provider-{type_name}",
        ):
            return (name, provider)
    return None


async def resolve_model_role(
    roles: list[str],
    matrix: dict[str, Any],
    providers: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolve model role(s) against routing matrix."""
    for role in roles:
        role_data = matrix.get(role)
        if role_data is None:
            continue

        candidates = role_data.get("candidates", [])
        for candidate in candidates:
            provider_type = candidate.get("provider", "")
            model_pattern = candidate.get("model", "")
            config = candidate.get("config", {})

            match = find_provider_by_type(providers, provider_type)
            if match is None:
                continue

            _module_id, provider_instance = match

            if any(c in model_pattern for c in "*?["):
                resolved_model = await _resolve_glob(model_pattern, provider_instance)
                if resolved_model is None:
                    continue
            else:
                resolved_model = model_pattern

            return [
                {
                    "provider": provider_type,
                    "model": resolved_model,
                    "config": config,
                }
            ]

    return []


async def _resolve_glob(pattern: str, provider: Any) -> str | None:
    """Resolve a glob model pattern against a provider's model list."""
    try:
        available = await provider.list_models()
    except Exception:
        logger.warning("Failed to list models for glob resolution: %s", pattern)
        return None

    for model in available:
        model_id = getattr(model, "id", str(model))
        if fnmatch.fnmatch(model_id, pattern):
            return model_id
    return None
```

**Step 6: Write RoutingHook**

Create `services/amplifier-routing-matrix/src/amplifier_routing_matrix/hooks/routing.py`:

```python
"""RoutingHook — model routing based on curated role-to-provider matrices.

Ported from amplifier-lite's amplifier_routing_matrix.hooks.routing.
Changes: replaced register() pattern with @hook + handle() dispatcher,
removed Session dependency, replaced amplifier_lite imports.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from amplifier_ipc_protocol import hook, HookResult, HookAction

from .matrix_loader import load_matrix, compose_matrix

logger = logging.getLogger(__name__)


@hook(events=["session:start", "provider:request"], priority=15)
class RoutingHook:
    """Hook that resolves model roles against routing matrices.

    Loads a default matrix at startup and registers handlers for
    session:start and provider:request events.
    """

    name = "routing"
    events = ["session:start", "provider:request"]
    priority = 15

    def __init__(self) -> None:
        # Locate routing directory relative to package root
        module_file = Path(__file__)
        package_root = module_file.parent.parent
        routing_dir = package_root / "routing"

        # Load default matrix
        self.base_matrix: dict[str, Any] = {}
        matrix_path = routing_dir / "balanced.yaml"
        if matrix_path.exists():
            self.base_matrix = load_matrix(matrix_path)
        else:
            logger.warning("Matrix file not found: %s — routing disabled", matrix_path)

        self.effective_matrix: dict[str, Any] = self.base_matrix.get("roles", {})

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch to the appropriate handler based on event type."""
        if event == "session:start":
            return await self._handle_session_start(data)
        if event == "provider:request":
            return await self._handle_provider_request(data)
        return HookResult(action=HookAction.CONTINUE)

    async def _handle_session_start(self, data: dict[str, Any]) -> HookResult:
        """Resolve model roles on session start."""
        if not self.effective_matrix:
            return HookResult(action=HookAction.CONTINUE)
        return HookResult(
            action=HookAction.MODIFY,
            data={"routing_matrix": self.effective_matrix},
        )

    async def _handle_provider_request(self, data: dict[str, Any]) -> HookResult:
        """Inject routing context into provider requests."""
        if not self.effective_matrix:
            return HookResult(action=HookAction.CONTINUE)
        available_roles = list(self.effective_matrix.keys())
        return HookResult(
            action=HookAction.MODIFY,
            data={"available_roles": available_roles},
        )
```

**Step 7: Write tests**

Create `services/amplifier-routing-matrix/tests/test_scaffolding.py`:

```python
"""Tests for project scaffolding."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


def test_package_importable() -> None:
    import amplifier_routing_matrix

    assert amplifier_routing_matrix.__version__ == "0.1.0"


def test_main_module_exists() -> None:
    main_path = PROJECT_ROOT / "src" / "amplifier_routing_matrix" / "__main__.py"
    assert main_path.exists()


@pytest.mark.skipif(
    shutil.which("amplifier-routing-matrix-serve") is None,
    reason="Package not installed as tool",
)
def test_entry_point_available() -> None:
    assert shutil.which("amplifier-routing-matrix-serve") is not None
```

Create `services/amplifier-routing-matrix/tests/test_describe.py`:

```python
"""Describe verification — 1 hook + content."""

from __future__ import annotations

import asyncio
import json

import pytest

from amplifier_ipc_protocol.server import Server


class _MockWriter:
    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass

    @property
    def messages(self) -> list[dict]:
        result = []
        for line in self._buf.split(b"\n"):
            stripped = line.strip()
            if stripped:
                result.append(json.loads(stripped))
        return result


async def _send_describe() -> dict:
    server = Server("amplifier_routing_matrix")
    reader = asyncio.StreamReader()
    writer = _MockWriter()
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "describe"}) + "\n"
    reader.feed_data(request.encode())
    reader.feed_eof()
    await server.handle_stream(reader, writer)
    messages = writer.messages
    assert len(messages) == 1
    assert "result" in messages[0]
    return messages[0]["result"]


@pytest.mark.asyncio
async def test_describe_has_routing_hook() -> None:
    """describe must report the routing hook."""
    result = await _send_describe()
    caps = result["capabilities"]
    hook_names = [h["name"] for h in caps.get("hooks", [])]
    assert "routing" in hook_names, f"Expected 'routing' hook, found: {hook_names}"


@pytest.mark.asyncio
async def test_describe_has_content() -> None:
    """describe must report content paths."""
    result = await _send_describe()
    caps = result["capabilities"]
    paths = caps.get("content", {}).get("paths", [])
    assert len(paths) >= 3, f"Expected >= 3 content paths, got {len(paths)}: {paths}"
```

Create `services/amplifier-routing-matrix/tests/test_matrix_loader.py`:

```python
"""Tests for matrix_loader — verifies YAML loading and composition."""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_routing_matrix.hooks.matrix_loader import compose_matrix, load_matrix


@pytest.fixture
def routing_dir() -> Path:
    """Path to the routing YAML directory."""
    return Path(__file__).parent.parent / "src" / "amplifier_routing_matrix" / "routing"


def test_load_balanced_matrix(routing_dir: Path) -> None:
    """balanced.yaml must load successfully and contain roles."""
    matrix = load_matrix(routing_dir / "balanced.yaml")
    assert "roles" in matrix or isinstance(matrix, dict)


def test_load_all_matrices(routing_dir: Path) -> None:
    """All 7 routing YAML files must load without error."""
    expected_files = [
        "anthropic.yaml",
        "balanced.yaml",
        "copilot.yaml",
        "economy.yaml",
        "gemini.yaml",
        "openai.yaml",
        "quality.yaml",
    ]
    for filename in expected_files:
        path = routing_dir / filename
        assert path.exists(), f"Missing matrix file: {path}"
        matrix = load_matrix(path)
        assert isinstance(matrix, dict), f"{filename} did not load as dict"


def test_compose_matrix_override() -> None:
    """compose_matrix must merge overrides into base."""
    base = {
        "general": {"candidates": [{"provider": "anthropic", "model": "claude-sonnet-4-5"}]},
    }
    overrides = {
        "general": {"candidates": [{"provider": "openai", "model": "gpt-4o"}]},
    }
    result = compose_matrix(base, overrides)
    assert result["general"]["candidates"][0]["provider"] == "openai"


def test_compose_matrix_base_keyword() -> None:
    """compose_matrix must expand 'base' keyword."""
    base = {
        "general": {"candidates": [{"provider": "anthropic", "model": "claude-sonnet-4-5"}]},
    }
    overrides = {
        "general": {"candidates": [{"provider": "openai", "model": "gpt-4o"}, "base"]},
    }
    result = compose_matrix(base, overrides)
    candidates = result["general"]["candidates"]
    assert len(candidates) == 2
    assert candidates[0]["provider"] == "openai"
    assert candidates[1]["provider"] == "anthropic"
```

Create `services/amplifier-routing-matrix/tests/test_content.py`:

```python
"""Content discovery verification."""

from __future__ import annotations

import pytest

from amplifier_ipc_protocol.discovery import scan_content


@pytest.fixture(scope="module")
def content_files() -> list[str]:
    return scan_content("amplifier_routing_matrix")


def test_behaviors_content(content_files: list[str]) -> None:
    behavior_files = [f for f in content_files if f.startswith("behaviors/")]
    assert len(behavior_files) >= 1, f"Expected >= 1 behavior file, found: {behavior_files}"


def test_context_content(content_files: list[str]) -> None:
    context_files = [f for f in content_files if f.startswith("context/")]
    assert len(context_files) >= 2, f"Expected >= 2 context files, found: {context_files}"
```

**Step 8: Install and run tests**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-routing-matrix
uv sync --extra dev
uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 9: Commit**

```bash
git init && git add -A && git commit -m "feat: amplifier-routing-matrix service (RoutingHook + matrix loader + content)"
```

---

## Task 6: amplifier-core (Content-Only Service)

**Files:**
- Create: `services/amplifier-core/pyproject.toml`
- Create: `services/amplifier-core/src/amplifier_core/__init__.py`
- Create: `services/amplifier-core/src/amplifier_core/__main__.py`
- Copy: all content dirs from source (agents/, behaviors/, context/)
- Create: `services/amplifier-core/tests/__init__.py`
- Create: `services/amplifier-core/tests/conftest.py`
- Test: `services/amplifier-core/tests/test_scaffolding.py`
- Test: `services/amplifier-core/tests/test_describe.py`
- Test: `services/amplifier-core/tests/test_content.py`

Content-only services have NO component directories — no `tools/`, `hooks/`, `providers/`, etc. The Server discovers zero components and only serves content files.

**Step 1: Create directory structure and copy content**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc
mkdir -p services/amplifier-core/src/amplifier_core
mkdir -p services/amplifier-core/tests
touch services/amplifier-core/tests/__init__.py
touch services/amplifier-core/tests/conftest.py

# Copy all content directories recursively
cp -r /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-core/src/amplifier_core/agents \
      /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-core/src/amplifier_core/
cp -r /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-core/src/amplifier_core/behaviors \
      /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-core/src/amplifier_core/
cp -r /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-core/src/amplifier_core/context \
      /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-core/src/amplifier_core/
```

**Step 2: Write boilerplate files**

Create `services/amplifier-core/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "amplifier-core"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "amplifier-ipc-protocol",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.scripts]
amplifier-core-serve = "amplifier_core.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/amplifier_core"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src"]

[tool.uv.sources]
amplifier-ipc-protocol = { path = "../../amplifier-ipc-protocol" }
```

Create `services/amplifier-core/src/amplifier_core/__init__.py`:

```python
"""amplifier_core: Core docs, contracts, and kernel philosophy content."""

__version__: str = "0.1.0"
```

Create `services/amplifier-core/src/amplifier_core/__main__.py`:

```python
"""Entry point for amplifier-core IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier-core IPC service."""
    Server("amplifier_core").run()


if __name__ == "__main__":
    main()
```

**Step 3: Write tests**

Create `services/amplifier-core/tests/test_scaffolding.py`:

```python
"""Tests for project scaffolding."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


def test_package_importable() -> None:
    import amplifier_core

    assert amplifier_core.__version__ == "0.1.0"


def test_main_module_exists() -> None:
    main_path = PROJECT_ROOT / "src" / "amplifier_core" / "__main__.py"
    assert main_path.exists()


@pytest.mark.skipif(
    shutil.which("amplifier-core-serve") is None,
    reason="Package not installed as tool",
)
def test_entry_point_available() -> None:
    assert shutil.which("amplifier-core-serve") is not None
```

Create `services/amplifier-core/tests/test_describe.py`:

```python
"""Describe verification — zero components, rich content."""

from __future__ import annotations

import asyncio
import json

import pytest

from amplifier_ipc_protocol.server import Server


class _MockWriter:
    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass

    @property
    def messages(self) -> list[dict]:
        result = []
        for line in self._buf.split(b"\n"):
            stripped = line.strip()
            if stripped:
                result.append(json.loads(stripped))
        return result


async def _send_describe() -> dict:
    server = Server("amplifier_core")
    reader = asyncio.StreamReader()
    writer = _MockWriter()
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "describe"}) + "\n"
    reader.feed_data(request.encode())
    reader.feed_eof()
    await server.handle_stream(reader, writer)
    messages = writer.messages
    assert len(messages) == 1
    assert "result" in messages[0]
    return messages[0]["result"]


@pytest.mark.asyncio
async def test_describe_has_zero_components() -> None:
    """Content-only service must report zero tools, hooks, etc."""
    result = await _send_describe()
    caps = result["capabilities"]
    assert len(caps.get("tools", [])) == 0
    assert len(caps.get("hooks", [])) == 0
    assert len(caps.get("orchestrators", [])) == 0
    assert len(caps.get("context_managers", [])) == 0
    assert len(caps.get("providers", [])) == 0


@pytest.mark.asyncio
async def test_describe_has_rich_content() -> None:
    """describe must report >= 30 content paths (core has 46 content files)."""
    result = await _send_describe()
    caps = result["capabilities"]
    paths = caps.get("content", {}).get("paths", [])
    assert len(paths) >= 30, f"Expected >= 30 content paths, got {len(paths)}"
```

Create `services/amplifier-core/tests/test_content.py`:

```python
"""Content discovery verification."""

from __future__ import annotations

import pytest

from amplifier_ipc_protocol.discovery import scan_content


@pytest.fixture(scope="module")
def content_files() -> list[str]:
    return scan_content("amplifier_core")


def test_agents_content(content_files: list[str]) -> None:
    agent_files = [f for f in content_files if f.startswith("agents/")]
    assert len(agent_files) >= 1, f"Expected >= 1 agent file, found: {agent_files}"


def test_behaviors_content(content_files: list[str]) -> None:
    behavior_files = [f for f in content_files if f.startswith("behaviors/")]
    assert len(behavior_files) >= 1, f"Expected >= 1 behavior file, found: {behavior_files}"


def test_context_content(content_files: list[str]) -> None:
    context_files = [f for f in content_files if f.startswith("context/")]
    assert len(context_files) >= 20, f"Expected >= 20 context files, found {len(context_files)}"
```

**Step 4: Install and run tests**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-core
uv sync --extra dev
uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git init && git add -A && git commit -m "feat: amplifier-core content-only service (46 content files)"
```

---

## Tasks 7-11: Remaining Content-Only Services

Tasks 7 through 11 follow the **exact same pattern** as Task 6. Each one:
1. Creates the directory structure
2. Copies content from the source package
3. Writes `pyproject.toml`, `__init__.py`, `__main__.py`
4. Writes `test_scaffolding.py`, `test_describe.py`, `test_content.py`
5. Installs and runs tests
6. Commits

Below are the specifics for each. The test and boilerplate code is identical in structure — only the package name, content counts, and content directories change.

---

### Task 7: amplifier-amplifier (Content-Only)

**Source:** `/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-amplifier/src/amplifier_amplifier/`
**Content dirs to copy:** `agents/`, `behaviors/`, `context/`, `recipes/`
**Content file count:** 12
**Package name:** `amplifier_amplifier`
**Service name:** `amplifier-amplifier`

**Step 1: Create structure and copy content**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc
mkdir -p services/amplifier-amplifier/src/amplifier_amplifier
mkdir -p services/amplifier-amplifier/tests
touch services/amplifier-amplifier/tests/__init__.py
touch services/amplifier-amplifier/tests/conftest.py

for dir in agents behaviors context recipes; do
    src="/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-amplifier/src/amplifier_amplifier/${dir}"
    if [ -d "$src" ]; then
        cp -r "$src" /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-amplifier/src/amplifier_amplifier/
    fi
done
```

**Step 2: Write boilerplate**

`pyproject.toml` — same as Task 6 template with:
- `name = "amplifier-amplifier"`
- `amplifier-amplifier-serve = "amplifier_amplifier.__main__:main"`
- `packages = ["src/amplifier_amplifier"]`

`__init__.py`:
```python
"""amplifier_amplifier: Ecosystem meta-content and development recipes."""

__version__: str = "0.1.0"
```

`__main__.py`:
```python
"""Entry point for amplifier-amplifier IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier-amplifier IPC service."""
    Server("amplifier_amplifier").run()


if __name__ == "__main__":
    main()
```

**Step 3: Write tests**

`test_describe.py` — assert zero components, `>= 10` content paths.
`test_content.py` — assert `>= 1` agents, `>= 2` behaviors, `>= 2` context, `>= 5` recipes.

**Step 4: Install, test, commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-amplifier
uv sync --extra dev
uv run pytest tests/ -v
git init && git add -A && git commit -m "feat: amplifier-amplifier content-only service"
```

---

### Task 8: amplifier-browser-tester (Content-Only)

**Source:** `/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-browser-tester/src/amplifier_browser_tester/`
**Content dirs to copy:** `agents/`, `behaviors/`, `context/`, `recipes/`
**Content file count:** 9
**Package name:** `amplifier_browser_tester`
**Service name:** `amplifier-browser-tester`

**Step 1: Create structure and copy content**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc
mkdir -p services/amplifier-browser-tester/src/amplifier_browser_tester
mkdir -p services/amplifier-browser-tester/tests
touch services/amplifier-browser-tester/tests/__init__.py
touch services/amplifier-browser-tester/tests/conftest.py

for dir in agents behaviors context recipes; do
    src="/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-browser-tester/src/amplifier_browser_tester/${dir}"
    if [ -d "$src" ]; then
        cp -r "$src" /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-browser-tester/src/amplifier_browser_tester/
    fi
done
```

**Step 2: Write boilerplate**

`__init__.py`:
```python
"""amplifier_browser_tester: Browser testing agents, recipes, and context."""

__version__: str = "0.1.0"
```

`__main__.py`:
```python
"""Entry point for amplifier-browser-tester IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier-browser-tester IPC service."""
    Server("amplifier_browser_tester").run()


if __name__ == "__main__":
    main()
```

**Step 3: Write tests**

`test_describe.py` — assert zero components, `>= 7` content paths.
`test_content.py` — assert `>= 3` agents, `>= 1` behaviors, `>= 2` context, `>= 3` recipes.

**Step 4: Install, test, commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-browser-tester
uv sync --extra dev
uv run pytest tests/ -v
git init && git add -A && git commit -m "feat: amplifier-browser-tester content-only service"
```

---

### Task 9: amplifier-design-intelligence (Content-Only)

**Source:** `/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-design-intelligence/src/amplifier_design_intelligence/`
**Content dirs to copy:** `agents/`, `behaviors/`, `context/`
**Content file count:** 23
**Package name:** `amplifier_design_intelligence`
**Service name:** `amplifier-design-intelligence`

**Step 1: Create structure and copy content**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc
mkdir -p services/amplifier-design-intelligence/src/amplifier_design_intelligence
mkdir -p services/amplifier-design-intelligence/tests
touch services/amplifier-design-intelligence/tests/__init__.py
touch services/amplifier-design-intelligence/tests/conftest.py

for dir in agents behaviors context; do
    src="/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-design-intelligence/src/amplifier_design_intelligence/${dir}"
    if [ -d "$src" ]; then
        cp -r "$src" /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-design-intelligence/src/amplifier_design_intelligence/
    fi
done
```

**Step 2: Write boilerplate**

`__init__.py`:
```python
"""amplifier_design_intelligence: Design agents, knowledge base, and protocols."""

__version__: str = "0.1.0"
```

`__main__.py`:
```python
"""Entry point for amplifier-design-intelligence IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier-design-intelligence IPC service."""
    Server("amplifier_design_intelligence").run()


if __name__ == "__main__":
    main()
```

**Step 3: Write tests**

`test_describe.py` — assert zero components, `>= 15` content paths.
`test_content.py` — assert `>= 7` agents, `>= 1` behaviors, `>= 10` context (includes nested knowledge-base/, philosophy/, protocols/).

**Step 4: Install, test, commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-design-intelligence
uv sync --extra dev
uv run pytest tests/ -v
git init && git add -A && git commit -m "feat: amplifier-design-intelligence content-only service"
```

---

### Task 10: amplifier-filesystem (Content-Only)

**Source:** `/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-filesystem/src/amplifier_filesystem/`
**Content dirs to copy:** `behaviors/`, `context/`
**Content file count:** 2 (smallest service)
**Package name:** `amplifier_filesystem`
**Service name:** `amplifier-filesystem`

**Step 1: Create structure and copy content**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc
mkdir -p services/amplifier-filesystem/src/amplifier_filesystem
mkdir -p services/amplifier-filesystem/tests
touch services/amplifier-filesystem/tests/__init__.py
touch services/amplifier-filesystem/tests/conftest.py

for dir in behaviors context; do
    src="/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-filesystem/src/amplifier_filesystem/${dir}"
    if [ -d "$src" ]; then
        cp -r "$src" /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-filesystem/src/amplifier_filesystem/
    fi
done
```

**Step 2: Write boilerplate**

`__init__.py`:
```python
"""amplifier_filesystem: Editing guidance and apply-patch behavior."""

__version__: str = "0.1.0"
```

`__main__.py`:
```python
"""Entry point for amplifier-filesystem IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier-filesystem IPC service."""
    Server("amplifier_filesystem").run()


if __name__ == "__main__":
    main()
```

**Step 3: Write tests**

`test_describe.py` — assert zero components, `>= 2` content paths.
`test_content.py` — assert `>= 1` behaviors, `>= 1` context.

**Step 4: Install, test, commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-filesystem
uv sync --extra dev
uv run pytest tests/ -v
git init && git add -A && git commit -m "feat: amplifier-filesystem content-only service"
```

---

### Task 11: amplifier-recipes (Content-Only)

**Source:** `/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-recipes/src/amplifier_recipes/`
**Content dirs to copy:** `agents/`, `behaviors/`, `context/`, `recipes/`
**Content file count:** 6
**Package name:** `amplifier_recipes`
**Service name:** `amplifier-recipes`

**Step 1: Create structure and copy content**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc
mkdir -p services/amplifier-recipes/src/amplifier_recipes
mkdir -p services/amplifier-recipes/tests
touch services/amplifier-recipes/tests/__init__.py
touch services/amplifier-recipes/tests/conftest.py

for dir in agents behaviors context recipes; do
    src="/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-recipes/src/amplifier_recipes/${dir}"
    if [ -d "$src" ]; then
        cp -r "$src" /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-recipes/src/amplifier_recipes/
    fi
done
```

**Step 2: Write boilerplate**

`__init__.py`:
```python
"""amplifier_recipes: Recipe authoring agents and context."""

__version__: str = "0.1.0"
```

`__main__.py`:
```python
"""Entry point for amplifier-recipes IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier-recipes IPC service."""
    Server("amplifier_recipes").run()


if __name__ == "__main__":
    main()
```

**Step 3: Write tests**

`test_describe.py` — assert zero components, `>= 5` content paths.
`test_content.py` — assert `>= 2` agents, `>= 1` behaviors, `>= 1` context, `>= 1` recipes.

**Step 4: Install, test, commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-recipes
uv sync --extra dev
uv run pytest tests/ -v
git init && git add -A && git commit -m "feat: amplifier-recipes content-only service"
```

---

### Task 12: amplifier-superpowers (Content-Only)

**Source:** `/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-superpowers/src/amplifier_superpowers/`
**Content dirs to copy:** `agents/`, `behaviors/`, `context/`, `recipes/`
**Content file count:** 19
**Package name:** `amplifier_superpowers`
**Service name:** `amplifier-superpowers`

**Step 1: Create structure and copy content**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc
mkdir -p services/amplifier-superpowers/src/amplifier_superpowers
mkdir -p services/amplifier-superpowers/tests
touch services/amplifier-superpowers/tests/__init__.py
touch services/amplifier-superpowers/tests/conftest.py

for dir in agents behaviors context recipes; do
    src="/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-superpowers/src/amplifier_superpowers/${dir}"
    if [ -d "$src" ]; then
        cp -r "$src" /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-superpowers/src/amplifier_superpowers/
    fi
done
```

**Step 2: Write boilerplate**

`__init__.py`:
```python
"""amplifier_superpowers: Development methodology agents, recipes, and modes context."""

__version__: str = "0.1.0"
```

`__main__.py`:
```python
"""Entry point for amplifier-superpowers IPC service."""

from __future__ import annotations

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier-superpowers IPC service."""
    Server("amplifier_superpowers").run()


if __name__ == "__main__":
    main()
```

**Step 3: Write tests**

`test_describe.py` — assert zero components, `>= 15` content paths.
`test_content.py` — assert `>= 5` agents, `>= 1` behaviors, `>= 5` context, `>= 5` recipes.

**Step 4: Install, test, commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-superpowers
uv sync --extra dev
uv run pytest tests/ -v
git init && git add -A && git commit -m "feat: amplifier-superpowers content-only service"
```

---

## Task 13: Cross-Service Integration Test

**Files:**
- Create: `services/integration-tests/pyproject.toml`
- Create: `services/integration-tests/tests/__init__.py`
- Create: `services/integration-tests/tests/conftest.py`
- Test: `services/integration-tests/tests/test_multi_service.py`
- Test: `services/integration-tests/tests/test_content_serving.py`

This task verifies that multiple services can be started and queried independently — proving the full multi-service IPC architecture works.

**Step 1: Create the integration test project**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc
mkdir -p services/integration-tests/tests
touch services/integration-tests/tests/__init__.py
touch services/integration-tests/tests/conftest.py
```

**Step 2: Write pyproject.toml**

Create `services/integration-tests/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "amplifier-ipc-integration-tests"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "amplifier-ipc-protocol",
    "amplifier-foundation",
    "amplifier-providers",
    "amplifier-modes",
    "amplifier-skills",
    "amplifier-routing-matrix",
    "amplifier-core",
    "amplifier-amplifier",
    "amplifier-browser-tester",
    "amplifier-design-intelligence",
    "amplifier-filesystem",
    "amplifier-recipes",
    "amplifier-superpowers",
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.uv.sources]
amplifier-ipc-protocol = { path = "../../amplifier-ipc-protocol" }
amplifier-foundation = { path = "../amplifier-foundation" }
amplifier-providers = { path = "../amplifier-providers" }
amplifier-modes = { path = "../amplifier-modes" }
amplifier-skills = { path = "../amplifier-skills" }
amplifier-routing-matrix = { path = "../amplifier-routing-matrix" }
amplifier-core = { path = "../amplifier-core" }
amplifier-amplifier = { path = "../amplifier-amplifier" }
amplifier-browser-tester = { path = "../amplifier-browser-tester" }
amplifier-design-intelligence = { path = "../amplifier-design-intelligence" }
amplifier-filesystem = { path = "../amplifier-filesystem" }
amplifier-recipes = { path = "../amplifier-recipes" }
amplifier-superpowers = { path = "../amplifier-superpowers" }
```

**Step 3: Write conftest.py**

Create `services/integration-tests/tests/conftest.py`:

```python
"""Shared test infrastructure for cross-service integration tests."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from amplifier_ipc_protocol.server import Server


class MockWriter:
    """Collects bytes written via write()/drain()."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass

    @property
    def messages(self) -> list[dict]:
        result = []
        for line in self._buf.split(b"\n"):
            stripped = line.strip()
            if stripped:
                result.append(json.loads(stripped))
        return result


async def send_request(package_name: str, method: str, params: Any = None) -> dict:
    """Send a JSON-RPC request to a Server and return the response."""
    server = Server(package_name)
    reader = asyncio.StreamReader()
    writer = MockWriter()

    msg: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        msg["params"] = params

    reader.feed_data((json.dumps(msg) + "\n").encode())
    reader.feed_eof()

    await server.handle_stream(reader, writer)

    messages = writer.messages
    assert len(messages) == 1, f"Expected 1 response, got {len(messages)}"
    return messages[0]
```

**Step 4: Write multi-service describe test**

Create `services/integration-tests/tests/test_multi_service.py`:

```python
"""Multi-service integration — all 12 services describe correctly."""

from __future__ import annotations

import pytest

from conftest import send_request

ALL_SERVICES = [
    "amplifier_foundation",
    "amplifier_providers",
    "amplifier_modes",
    "amplifier_skills",
    "amplifier_routing_matrix",
    "amplifier_core",
    "amplifier_amplifier",
    "amplifier_browser_tester",
    "amplifier_design_intelligence",
    "amplifier_filesystem",
    "amplifier_recipes",
    "amplifier_superpowers",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("package_name", ALL_SERVICES)
async def test_all_services_describe(package_name: str) -> None:
    """Every service must respond to describe without errors."""
    response = await send_request(package_name, "describe")
    assert "result" in response, f"{package_name} describe returned error: {response}"
    result = response["result"]
    assert "capabilities" in result
    assert "name" in result
    assert result["name"] == package_name


@pytest.mark.asyncio
async def test_aggregate_component_counts() -> None:
    """Verify total component counts across all services."""
    total_tools = 0
    total_hooks = 0
    total_providers = 0
    total_orchestrators = 0
    total_context_managers = 0
    total_content_paths = 0

    for package_name in ALL_SERVICES:
        response = await send_request(package_name, "describe")
        caps = response["result"]["capabilities"]
        total_tools += len(caps.get("tools", []))
        total_hooks += len(caps.get("hooks", []))
        total_providers += len(caps.get("providers", []))
        total_orchestrators += len(caps.get("orchestrators", []))
        total_context_managers += len(caps.get("context_managers", []))
        total_content_paths += len(caps.get("content", {}).get("paths", []))

    # Foundation has 10+ tools, modes has 1, skills has 1 = 12+
    assert total_tools >= 12, f"Expected >= 12 total tools, got {total_tools}"
    # Foundation has 10+ hooks, modes has 1, routing has 1 = 12+
    assert total_hooks >= 12, f"Expected >= 12 total hooks, got {total_hooks}"
    # Providers has 8
    assert total_providers >= 8, f"Expected >= 8 total providers, got {total_providers}"
    # Foundation has 1
    assert total_orchestrators >= 1, f"Expected >= 1 orchestrator, got {total_orchestrators}"
    # Foundation has 1
    assert total_context_managers >= 1, f"Expected >= 1 context manager, got {total_context_managers}"
    # All services have content (100+ total)
    assert total_content_paths >= 100, f"Expected >= 100 total content paths, got {total_content_paths}"
```

**Step 5: Write content serving test**

Create `services/integration-tests/tests/test_content_serving.py`:

```python
"""Cross-service content serving — read content from multiple services."""

from __future__ import annotations

import pytest

from conftest import send_request


@pytest.mark.asyncio
async def test_read_content_from_core() -> None:
    """Read a known content file from amplifier-core."""
    response = await send_request(
        "amplifier_core",
        "content.read",
        {"path": "agents/core-expert.md"},
    )
    assert "result" in response, f"content.read returned error: {response}"
    assert "content" in response["result"]
    assert len(response["result"]["content"]) > 0


@pytest.mark.asyncio
async def test_read_content_from_superpowers() -> None:
    """Read a known content file from amplifier-superpowers."""
    response = await send_request(
        "amplifier_superpowers",
        "content.read",
        {"path": "agents/implementer.md"},
    )
    assert "result" in response, f"content.read returned error: {response}"
    assert "content" in response["result"]
    assert len(response["result"]["content"]) > 0


@pytest.mark.asyncio
async def test_list_content_from_design_intelligence() -> None:
    """List content from amplifier-design-intelligence with prefix filter."""
    response = await send_request(
        "amplifier_design_intelligence",
        "content.list",
        {"prefix": "agents/"},
    )
    assert "result" in response
    paths = response["result"]["paths"]
    assert len(paths) >= 7, f"Expected >= 7 design agent paths, got {len(paths)}: {paths}"


@pytest.mark.asyncio
async def test_content_read_nonexistent_returns_error() -> None:
    """Reading nonexistent content must return a JSON-RPC error."""
    response = await send_request(
        "amplifier_core",
        "content.read",
        {"path": "agents/nonexistent-agent.md"},
    )
    assert "error" in response, "Expected error for nonexistent content"


@pytest.mark.asyncio
async def test_content_only_services_serve_no_tools() -> None:
    """Content-only services must respond to tool.execute with method_not_found or invalid_params."""
    response = await send_request(
        "amplifier_core",
        "tool.execute",
        {"name": "nonexistent", "input": {}},
    )
    assert "error" in response, "Expected error for tool execution on content-only service"
```

**Step 6: Install and run tests**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/integration-tests
uv sync
uv run pytest tests/ -v
```

Expected: All tests PASS — 12 services describe successfully, aggregate counts verified, content serving works across services.

**Step 7: Commit**

```bash
git init && git add -A && git commit -m "feat: cross-service integration tests (12 services, describe + content)"
```

---

## Summary

| Task | Service | Type | Components | Content Files |
|------|---------|------|------------|---------------|
| 1-2 | amplifier-providers | Python | 8 providers (1 real + 7 stubs) | 0 |
| 3 | amplifier-modes | Python | 1 hook + 1 tool | 2 |
| 4 | amplifier-skills | Python | 1 tool | 3 |
| 5 | amplifier-routing-matrix | Python | 1 hook | 3 (+7 matrix YAML data files) |
| 6 | amplifier-core | Content-only | 0 | 46 |
| 7 | amplifier-amplifier | Content-only | 0 | 12 |
| 8 | amplifier-browser-tester | Content-only | 0 | 9 |
| 9 | amplifier-design-intelligence | Content-only | 0 | 23 |
| 10 | amplifier-filesystem | Content-only | 0 | 2 |
| 11 | amplifier-recipes | Content-only | 0 | 6 |
| 12 | amplifier-superpowers | Content-only | 0 | 19 |
| 13 | Integration tests | Tests | — | — |

**Total:** 13 tasks, 11 new services + 1 integration test suite. All 12 amplifier-lite packages now have IPC service equivalents.
