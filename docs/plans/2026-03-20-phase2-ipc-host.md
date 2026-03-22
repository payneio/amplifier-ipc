# Phase 2: IPC Host Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Build `amplifier-ipc-host`, the central message bus that spawns service processes, discovers their capabilities, routes JSON-RPC 2.0 messages between the orchestrator and services, and manages session lifecycle.

**Architecture:** The host reads a YAML session config, spawns each listed service as a subprocess (stdin/stdout JSON-RPC 2.0), sends `describe` to build a routing table, assembles a system prompt from service content, then sends `orchestrator.execute` to the chosen orchestrator. It enters a routing loop: orchestrator requests (`request.tool_execute`, `request.hook_emit`, etc.) are dispatched to the appropriate service, streaming notifications are relayed to stdout, and messages are persisted to a JSONL transcript. On completion, all services are torn down.

**Tech Stack:** Python 3.11+, PyYAML, hatchling build system, pytest + pytest-asyncio. Depends on `amplifier-ipc-protocol` (Phase 1).

**Design Document:** `amplifier-ipc/docs/plans/2026-03-20-amplifier-ipc-architecture-design.md`

**Phase 1 (dependency):** `amplifier-ipc/amplifier-ipc-protocol/` — provides `Client`, `Server`, `read_message`, `write_message`, `JsonRpcError`, `make_error_response`, all Pydantic models (`ToolResult`, `HookResult`, `HookAction`, `Message`, etc.), and error code constants.

**Project Root:** `/data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host/`

---

## Final File Structure

When all tasks are complete, the project will look like this:

```
amplifier-ipc/amplifier-ipc-host/
├── pyproject.toml
├── src/amplifier_ipc_host/
│   ├── __init__.py
│   ├── __main__.py          # CLI: amplifier-ipc-host run session.yaml
│   ├── config.py            # Session config + settings parsing (YAML)
│   ├── lifecycle.py         # Spawn/teardown service subprocesses
│   ├── registry.py          # Capability registry from describe responses
│   ├── router.py            # Message routing + hook fan-out
│   ├── content.py           # Content resolution + system prompt assembly
│   ├── persistence.py       # Session transcript persistence (JSONL)
│   └── host.py              # Main Host class tying everything together
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_config.py
    ├── test_lifecycle.py
    ├── test_registry.py
    ├── test_router.py
    ├── test_content.py
    ├── test_persistence.py
    ├── test_host.py
    └── test_integration.py
```

---

## Reference: Phase 1 Protocol Library API

The host imports from `amplifier_ipc_protocol`. Here are the key APIs you'll use:

```python
# Framing (read/write JSON-RPC messages over asyncio streams)
from amplifier_ipc_protocol.framing import read_message, write_message

# Client (send JSON-RPC requests, match responses by id)
from amplifier_ipc_protocol.client import Client
#   client = Client(reader, writer, on_notification=callback)
#   result = await client.request("describe")
#   result = await client.request("tool.execute", {"name": "bash", "input": {...}})
#   await client.send_notification("stream.token", {"text": "hello"})

# Errors
from amplifier_ipc_protocol.errors import JsonRpcError, make_error_response
from amplifier_ipc_protocol.errors import INTERNAL_ERROR, INVALID_PARAMS, METHOD_NOT_FOUND

# Models (Pydantic v2 — use .model_dump(mode="json") to serialize)
from amplifier_ipc_protocol.models import (
    HookAction, HookResult, ToolResult, Message,
    ChatRequest, ChatResponse, ToolSpec, ToolCall,
)
```

The `Client` class takes `(reader: asyncio.StreamReader, writer, on_notification=None)`. The `writer` just needs `.write(bytes)` and `async .drain()` methods.

The `read_message(reader)` function returns `dict | None` (None on EOF). The `write_message(writer, dict)` function serializes to newline-delimited JSON.

---

## Conventions

- **Build system:** hatchling (matching Phase 1)
- **Test framework:** pytest with `pytest-asyncio`, `asyncio_mode = "auto"` in pyproject.toml
- **YAML parsing:** PyYAML (`import yaml`)
- **Test style:** Simple assertions, `@pytest.mark.asyncio` for async tests, `tmp_path` fixture for temp dirs
- **Run all tests:** `cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/ -v`
- **Run single test:** `cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_config.py::test_name -v`

---

### Task 1: Project Scaffolding

**Files:**
- Create: `amplifier-ipc-host/pyproject.toml`
- Create: `amplifier-ipc-host/src/amplifier_ipc_host/__init__.py`
- Create: `amplifier-ipc-host/tests/__init__.py`
- Create: `amplifier-ipc-host/tests/conftest.py`

**Step 1: Create pyproject.toml**

Create `amplifier-ipc-host/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "amplifier-ipc-host"
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
amplifier-ipc-host = "amplifier_ipc_host.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/amplifier_ipc_host"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src"]

[tool.uv.sources]
amplifier-ipc-protocol = { path = "../amplifier-ipc-protocol" }
```

**Step 2: Create __init__.py**

Create `amplifier-ipc-host/src/amplifier_ipc_host/__init__.py`:

```python
"""amplifier-ipc-host: Central message bus for Amplifier IPC services."""
```

**Step 3: Create test scaffolding**

Create `amplifier-ipc-host/tests/__init__.py`:

```python
```

(Empty file.)

Create `amplifier-ipc-host/tests/conftest.py`:

```python
from __future__ import annotations
```

**Step 4: Initialize the project and verify it installs**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && uv sync --dev
```
Expected: Resolves dependencies, installs `amplifier-ipc-protocol` from local path, installs `pyyaml`. No errors.

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -c "import amplifier_ipc_host; print('OK')"
```
Expected: Prints `OK`.

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -c "from amplifier_ipc_protocol import Client, Server; print('protocol OK')"
```
Expected: Prints `protocol OK` (verifies the dependency link works).

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && git init && git add -A && git commit -m "feat: scaffold amplifier-ipc-host project"
```

---

### Task 2: Config Parsing

**Files:**
- Create: `amplifier-ipc-host/src/amplifier_ipc_host/config.py`
- Create: `amplifier-ipc-host/tests/test_config.py`

**Step 1: Write the failing tests**

Create `amplifier-ipc-host/tests/test_config.py`:

```python
"""Tests for session config and settings parsing."""

from __future__ import annotations

from pathlib import Path

import yaml

from amplifier_ipc_host.config import (
    HostSettings,
    ServiceOverride,
    SessionConfig,
    load_settings,
    parse_session_config,
    resolve_service_command,
)


# ---------------------------------------------------------------------------
# SessionConfig parsing
# ---------------------------------------------------------------------------


def test_parse_minimal_session_config(tmp_path: Path) -> None:
    """Parses a minimal session config with services and component selections."""
    config_path = tmp_path / "session.yaml"
    config_path.write_text(yaml.dump({
        "session": {
            "services": ["amplifier-foundation-serve", "amplifier-providers-serve"],
            "orchestrator": "streaming",
            "context_manager": "simple",
            "provider": "anthropic",
        }
    }))

    config = parse_session_config(config_path)

    assert config.services == ["amplifier-foundation-serve", "amplifier-providers-serve"]
    assert config.orchestrator == "streaming"
    assert config.context_manager == "simple"
    assert config.provider == "anthropic"
    assert config.component_config == {}


def test_parse_session_config_with_component_config(tmp_path: Path) -> None:
    """Parses component config overrides from the config section."""
    config_path = tmp_path / "session.yaml"
    config_path.write_text(yaml.dump({
        "session": {
            "services": ["amplifier-foundation-serve"],
            "orchestrator": "streaming",
            "context_manager": "simple",
            "provider": "anthropic",
            "config": {
                "bash": {"timeout": 60},
                "streaming": {"max_iterations": 50},
            },
        }
    }))

    config = parse_session_config(config_path)

    assert config.component_config == {
        "bash": {"timeout": 60},
        "streaming": {"max_iterations": 50},
    }


def test_parse_session_config_missing_file() -> None:
    """Raises FileNotFoundError for a nonexistent config file."""
    import pytest

    with pytest.raises(FileNotFoundError):
        parse_session_config(Path("/tmp/nonexistent_session_config.yaml"))


def test_parse_session_config_missing_services(tmp_path: Path) -> None:
    """Raises ValueError when the services list is missing."""
    import pytest

    config_path = tmp_path / "session.yaml"
    config_path.write_text(yaml.dump({
        "session": {
            "orchestrator": "streaming",
            "context_manager": "simple",
            "provider": "anthropic",
        }
    }))

    with pytest.raises(ValueError, match="services"):
        parse_session_config(config_path)


# ---------------------------------------------------------------------------
# Settings loading
# ---------------------------------------------------------------------------


def test_load_settings_empty(tmp_path: Path, monkeypatch: object) -> None:
    """Returns empty HostSettings when no settings files exist."""
    settings = load_settings(
        user_settings_path=tmp_path / "user_settings.yaml",
        project_settings_path=tmp_path / "project_settings.yaml",
    )

    assert settings.service_overrides == {}


def test_load_settings_user_overrides(tmp_path: Path) -> None:
    """Loads service overrides from user settings under amplifier_ipc namespace."""
    user_path = tmp_path / "user_settings.yaml"
    user_path.write_text(yaml.dump({
        "amplifier_ipc": {
            "service_overrides": {
                "amplifier-providers-serve": {
                    "command": ["python", "-m", "amplifier_providers.server"],
                    "working_dir": "/home/dev/amplifier-providers",
                }
            }
        }
    }))

    settings = load_settings(
        user_settings_path=user_path,
        project_settings_path=tmp_path / "nonexistent.yaml",
    )

    assert "amplifier-providers-serve" in settings.service_overrides
    override = settings.service_overrides["amplifier-providers-serve"]
    assert override.command == ["python", "-m", "amplifier_providers.server"]
    assert override.working_dir == "/home/dev/amplifier-providers"


def test_load_settings_project_overrides_user(tmp_path: Path) -> None:
    """Project settings override user settings for the same service."""
    user_path = tmp_path / "user.yaml"
    user_path.write_text(yaml.dump({
        "amplifier_ipc": {
            "service_overrides": {
                "my-service": {
                    "command": ["user-cmd"],
                }
            }
        }
    }))

    project_path = tmp_path / "project.yaml"
    project_path.write_text(yaml.dump({
        "amplifier_ipc": {
            "service_overrides": {
                "my-service": {
                    "command": ["project-cmd"],
                }
            }
        }
    }))

    settings = load_settings(
        user_settings_path=user_path,
        project_settings_path=project_path,
    )

    assert settings.service_overrides["my-service"].command == ["project-cmd"]


# ---------------------------------------------------------------------------
# Service command resolution
# ---------------------------------------------------------------------------


def test_resolve_service_command_no_override() -> None:
    """Falls back to [service_name] when no override exists."""
    settings = HostSettings(service_overrides={})
    cmd, cwd = resolve_service_command("amplifier-foundation-serve", settings)

    assert cmd == ["amplifier-foundation-serve"]
    assert cwd is None


def test_resolve_service_command_with_override() -> None:
    """Uses the override command and working_dir when set."""
    settings = HostSettings(service_overrides={
        "my-svc": ServiceOverride(
            command=["python", "-m", "my_svc.server"],
            working_dir="/home/dev/my-svc",
        )
    })
    cmd, cwd = resolve_service_command("my-svc", settings)

    assert cmd == ["python", "-m", "my_svc.server"]
    assert cwd == "/home/dev/my-svc"


def test_resolve_service_command_override_no_working_dir() -> None:
    """Override with command but no working_dir returns None for cwd."""
    settings = HostSettings(service_overrides={
        "svc": ServiceOverride(command=["my-cmd"])
    })
    cmd, cwd = resolve_service_command("svc", settings)

    assert cmd == ["my-cmd"]
    assert cwd is None
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_config.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_host.config'`

**Step 3: Write the implementation**

Create `amplifier-ipc-host/src/amplifier_ipc_host/config.py`:

```python
"""Session config and settings parsing for amplifier-ipc-host.

Reads YAML session configs and settings overrides. Service overrides
are namespaced under ``amplifier_ipc`` in settings.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ServiceOverride:
    """Override for a service's spawn command and working directory."""

    command: list[str] = field(default_factory=list)
    working_dir: str | None = None


@dataclass
class HostSettings:
    """Aggregated settings from user and project settings files."""

    service_overrides: dict[str, ServiceOverride] = field(default_factory=dict)


@dataclass
class SessionConfig:
    """Parsed session configuration from a session YAML file."""

    services: list[str]
    orchestrator: str
    context_manager: str
    provider: str
    component_config: dict[str, dict[str, Any]] = field(default_factory=dict)


def parse_session_config(path: Path) -> SessionConfig:
    """Parse a session YAML file into a SessionConfig.

    Args:
        path: Path to the session YAML file.

    Returns:
        Parsed SessionConfig.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If required fields are missing.
    """
    if not path.exists():
        raise FileNotFoundError(f"Session config not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    session = raw.get("session", {})

    services = session.get("services")
    if not services:
        raise ValueError("Session config missing required field: services")

    return SessionConfig(
        services=services,
        orchestrator=session.get("orchestrator", ""),
        context_manager=session.get("context_manager", ""),
        provider=session.get("provider", ""),
        component_config=session.get("config", {}),
    )


def load_settings(
    *,
    user_settings_path: Path | None = None,
    project_settings_path: Path | None = None,
) -> HostSettings:
    """Load and merge settings from user and project settings files.

    Project settings override user settings for the same service.
    Overrides are read from ``amplifier_ipc.service_overrides``.

    Args:
        user_settings_path: Path to user-level settings (~/.amplifier/settings.yaml).
        project_settings_path: Path to project-level settings (.amplifier/settings.yaml).

    Returns:
        Merged HostSettings.
    """
    merged_overrides: dict[str, ServiceOverride] = {}

    # User settings first (lower priority)
    if user_settings_path is not None:
        user_overrides = _load_overrides_from_file(user_settings_path)
        merged_overrides.update(user_overrides)

    # Project settings second (higher priority — overwrites user)
    if project_settings_path is not None:
        project_overrides = _load_overrides_from_file(project_settings_path)
        merged_overrides.update(project_overrides)

    return HostSettings(service_overrides=merged_overrides)


def _load_overrides_from_file(path: Path) -> dict[str, ServiceOverride]:
    """Load service overrides from a single settings file.

    Returns an empty dict if the file doesn't exist or has no overrides.
    """
    if not path.exists():
        return {}

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        return {}

    ipc_section = raw.get("amplifier_ipc", {})
    if not isinstance(ipc_section, dict):
        return {}

    raw_overrides = ipc_section.get("service_overrides", {})
    if not isinstance(raw_overrides, dict):
        return {}

    result: dict[str, ServiceOverride] = {}
    for svc_name, override_data in raw_overrides.items():
        if not isinstance(override_data, dict):
            continue
        result[svc_name] = ServiceOverride(
            command=override_data.get("command", []),
            working_dir=override_data.get("working_dir"),
        )

    return result


def resolve_service_command(
    service_name: str, settings: HostSettings
) -> tuple[list[str], str | None]:
    """Resolve the command and working directory for a service.

    Checks settings overrides first, falls back to [service_name] for PATH lookup.

    Args:
        service_name: The service name from the session config.
        settings: Loaded host settings.

    Returns:
        Tuple of (command_list, working_dir_or_None).
    """
    override = settings.service_overrides.get(service_name)
    if override is not None and override.command:
        return override.command, override.working_dir
    return [service_name], None
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_config.py -v
```
Expected: All 9 tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && git add -A && git commit -m "feat: config parsing for session YAML and settings overrides"
```

---

### Task 3: Service Lifecycle

**Files:**
- Create: `amplifier-ipc-host/src/amplifier_ipc_host/lifecycle.py`
- Create: `amplifier-ipc-host/tests/test_lifecycle.py`

**Step 1: Write the failing tests**

Create `amplifier-ipc-host/tests/test_lifecycle.py`:

```python
"""Tests for service process lifecycle management."""

from __future__ import annotations

import asyncio

import pytest

from amplifier_ipc_host.lifecycle import ServiceProcess, shutdown_service, spawn_service


@pytest.mark.asyncio
async def test_spawn_service_creates_process() -> None:
    """spawn_service starts a subprocess and returns a ServiceProcess with a Client."""
    # Use a simple command that reads stdin and exits on EOF
    svc = await spawn_service("test-svc", ["python", "-c", "import sys; sys.stdin.read()"])
    try:
        assert isinstance(svc, ServiceProcess)
        assert svc.name == "test-svc"
        assert svc.process.returncode is None  # still running
        assert svc.client is not None
    finally:
        svc.process.kill()
        await svc.process.wait()


@pytest.mark.asyncio
async def test_spawn_service_bad_command() -> None:
    """spawn_service raises if the command does not exist."""
    with pytest.raises((FileNotFoundError, OSError)):
        await spawn_service("bad", ["/nonexistent/command/xyz123"])


@pytest.mark.asyncio
async def test_shutdown_service_graceful() -> None:
    """shutdown_service sends SIGTERM and the process exits cleanly."""
    svc = await spawn_service("test-svc", ["python", "-c", "import sys; sys.stdin.read()"])
    await shutdown_service(svc, timeout=2.0)

    assert svc.process.returncode is not None  # process has exited


@pytest.mark.asyncio
async def test_shutdown_service_force_kill() -> None:
    """shutdown_service force-kills a process that ignores SIGTERM."""
    # This process traps SIGTERM and keeps running
    code = (
        "import signal, time; "
        "signal.signal(signal.SIGTERM, lambda *a: None); "
        "time.sleep(60)"
    )
    svc = await spawn_service("stubborn", ["python", "-c", code])
    await shutdown_service(svc, timeout=0.5)

    assert svc.process.returncode is not None  # force-killed
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_lifecycle.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_host.lifecycle'`

**Step 3: Write the implementation**

Create `amplifier-ipc-host/src/amplifier_ipc_host/lifecycle.py`:

```python
"""Service process lifecycle management for amplifier-ipc-host.

Spawns service subprocesses with stdin/stdout JSON-RPC 2.0 communication
and provides graceful shutdown with force-kill fallback.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from amplifier_ipc_protocol.client import Client

logger = logging.getLogger(__name__)


@dataclass
class ServiceProcess:
    """A running service subprocess with its JSON-RPC client.

    Attributes:
        name: The service name (from session config).
        process: The asyncio subprocess.
        client: JSON-RPC Client connected to the process's stdin/stdout.
    """

    name: str
    process: asyncio.subprocess.Process
    client: Client


async def spawn_service(
    name: str,
    command: list[str],
    working_dir: str | None = None,
) -> ServiceProcess:
    """Spawn a service as an asyncio subprocess.

    The subprocess's stdin and stdout are piped for JSON-RPC communication.
    A Client is attached to the process's stdout (reader) and stdin (writer).

    Args:
        name: Service name for identification.
        command: Command list to execute (e.g. ["amplifier-foundation-serve"]).
        working_dir: Optional working directory for the subprocess.

    Returns:
        A ServiceProcess with the running process and attached Client.

    Raises:
        FileNotFoundError: If the command is not found.
        OSError: If the process cannot be started.
    """
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
    )

    # stdout is the reader (service writes responses here)
    # stdin is the writer (we write requests here)
    assert process.stdout is not None
    assert process.stdin is not None

    client = Client(
        reader=process.stdout,
        writer=process.stdin,
    )

    return ServiceProcess(name=name, process=process, client=client)


async def shutdown_service(service: ServiceProcess, timeout: float = 5.0) -> None:
    """Gracefully shut down a service process.

    Sends SIGTERM first, waits up to *timeout* seconds, then sends SIGKILL.

    Args:
        service: The service to shut down.
        timeout: Seconds to wait after SIGTERM before force-killing.
    """
    proc = service.process

    if proc.returncode is not None:
        return  # already exited

    # Close stdin to signal EOF to the service
    if proc.stdin is not None:
        proc.stdin.close()

    try:
        proc.terminate()
    except ProcessLookupError:
        return  # already gone

    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Service %r did not exit after SIGTERM, sending SIGKILL", service.name)
        try:
            proc.kill()
        except ProcessLookupError:
            return
        await proc.wait()
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_lifecycle.py -v
```
Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && git add -A && git commit -m "feat: service process lifecycle (spawn + graceful shutdown)"
```

---

### Task 4: Capability Registry

**Files:**
- Create: `amplifier-ipc-host/src/amplifier_ipc_host/registry.py`
- Create: `amplifier-ipc-host/tests/test_registry.py`

**Step 1: Write the failing tests**

Create `amplifier-ipc-host/tests/test_registry.py`:

```python
"""Tests for the capability registry built from describe responses."""

from __future__ import annotations

import pytest

from amplifier_ipc_host.registry import CapabilityRegistry


# ---------------------------------------------------------------------------
# Helpers — fake describe results
# ---------------------------------------------------------------------------


def _foundation_describe() -> dict:
    """Describe result from a foundation-like service."""
    return {
        "name": "amplifier_foundation",
        "capabilities": {
            "tools": [
                {"name": "bash", "description": "Run shell commands", "input_schema": {}},
                {"name": "read_file", "description": "Read a file", "input_schema": {}},
            ],
            "hooks": [
                {"name": "approval", "events": ["tool:pre"], "priority": 10},
                {"name": "logging", "events": ["tool:pre", "tool:post"], "priority": 100},
            ],
            "orchestrators": [{"name": "streaming"}],
            "context_managers": [{"name": "simple"}],
            "providers": [],
            "content": {"paths": ["agents/explorer.md", "context/shared.md"]},
        },
    }


def _providers_describe() -> dict:
    """Describe result from a providers-like service."""
    return {
        "name": "amplifier_providers",
        "capabilities": {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [{"name": "anthropic"}, {"name": "openai"}],
            "content": {"paths": []},
        },
    }


def _modes_describe() -> dict:
    """Describe result from a modes-like service."""
    return {
        "name": "amplifier_modes",
        "capabilities": {
            "tools": [{"name": "mode", "description": "Switch modes", "input_schema": {}}],
            "hooks": [
                {"name": "mode_hook", "events": ["tool:pre", "prompt:submit"], "priority": 5},
            ],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": {"paths": ["context/modes.md"]},
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_register_and_lookup_tool() -> None:
    """Tools are indexed by name and map to the correct service key."""
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())

    assert registry.get_tool_service("bash") == "foundation"
    assert registry.get_tool_service("read_file") == "foundation"


def test_lookup_unknown_tool() -> None:
    """Returns None for tools not found in any service."""
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())

    assert registry.get_tool_service("nonexistent") is None


def test_register_and_lookup_hook_services() -> None:
    """Hook services are returned sorted by priority for a given event."""
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())
    registry.register("modes", _modes_describe())

    # tool:pre has: modes/mode_hook(5), foundation/approval(10), foundation/logging(100)
    hooks = registry.get_hook_services("tool:pre")
    service_names = [h["service_key"] for h in hooks]
    priorities = [h["priority"] for h in hooks]

    assert priorities == sorted(priorities)  # ascending order
    assert "modes" in service_names
    assert "foundation" in service_names


def test_lookup_hooks_unknown_event() -> None:
    """Returns empty list for events with no registered hooks."""
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())

    assert registry.get_hook_services("unknown:event") == []


def test_register_and_lookup_orchestrator() -> None:
    """Named orchestrator maps to the correct service key."""
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())

    assert registry.get_orchestrator_service("streaming") == "foundation"
    assert registry.get_orchestrator_service("nonexistent") is None


def test_register_and_lookup_context_manager() -> None:
    """Named context manager maps to the correct service key."""
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())

    assert registry.get_context_manager_service("simple") == "foundation"
    assert registry.get_context_manager_service("nonexistent") is None


def test_register_and_lookup_provider() -> None:
    """Named provider maps to the correct service key."""
    registry = CapabilityRegistry()
    registry.register("providers", _providers_describe())

    assert registry.get_provider_service("anthropic") == "providers"
    assert registry.get_provider_service("openai") == "providers"
    assert registry.get_provider_service("nonexistent") is None


def test_get_all_tool_specs() -> None:
    """Aggregates tool specs from all registered services."""
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())
    registry.register("modes", _modes_describe())

    specs = registry.get_all_tool_specs()
    names = {s["name"] for s in specs}

    assert names == {"bash", "read_file", "mode"}


def test_get_all_hook_descriptors() -> None:
    """Aggregates hook descriptors from all registered services."""
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())
    registry.register("modes", _modes_describe())

    descriptors = registry.get_all_hook_descriptors()
    names = {d["name"] for d in descriptors}

    assert names == {"approval", "logging", "mode_hook"}


def test_get_content_services() -> None:
    """Maps service keys to their content path lists."""
    registry = CapabilityRegistry()
    registry.register("foundation", _foundation_describe())
    registry.register("providers", _providers_describe())
    registry.register("modes", _modes_describe())

    content = registry.get_content_services()

    assert "agents/explorer.md" in content["foundation"]
    assert content["providers"] == []
    assert "context/modes.md" in content["modes"]
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_registry.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_host.registry'`

**Step 3: Write the implementation**

Create `amplifier-ipc-host/src/amplifier_ipc_host/registry.py`:

```python
"""Capability registry built from service describe responses.

Maps tool names, hook events, orchestrator/context_manager/provider names
to their owning service keys so the router can dispatch requests.
"""

from __future__ import annotations

from typing import Any


class CapabilityRegistry:
    """Registry of service capabilities built from ``describe`` responses.

    Service keys are arbitrary strings chosen by the caller (e.g. the key
    used in the services dict). All lookups return service keys, not service
    objects — the caller maps keys back to ServiceProcess instances.
    """

    def __init__(self) -> None:
        self._tool_to_service: dict[str, str] = {}
        self._hook_entries: list[dict[str, Any]] = []
        self._orchestrator_to_service: dict[str, str] = {}
        self._context_manager_to_service: dict[str, str] = {}
        self._provider_to_service: dict[str, str] = {}
        self._content_by_service: dict[str, list[str]] = {}
        self._all_tool_specs: list[dict[str, Any]] = []
        self._all_hook_descriptors: list[dict[str, Any]] = []

    def register(self, service_key: str, describe_result: dict[str, Any]) -> None:
        """Register capabilities from a single service's describe response.

        Args:
            service_key: Key identifying this service (used in all lookups).
            describe_result: The ``result`` dict from a ``describe`` JSON-RPC response.
        """
        caps = describe_result.get("capabilities", {})

        # Tools
        for tool_info in caps.get("tools", []):
            name = tool_info.get("name", "")
            if name:
                self._tool_to_service[name] = service_key
                self._all_tool_specs.append(tool_info)

        # Hooks
        for hook_info in caps.get("hooks", []):
            hook_name = hook_info.get("name", "")
            events = hook_info.get("events", [])
            priority = hook_info.get("priority", 0)
            for event in events:
                self._hook_entries.append({
                    "service_key": service_key,
                    "hook_name": hook_name,
                    "event": event,
                    "priority": priority,
                })
            self._all_hook_descriptors.append(hook_info)

        # Orchestrators
        for orch_info in caps.get("orchestrators", []):
            name = orch_info.get("name", "")
            if name:
                self._orchestrator_to_service[name] = service_key

        # Context managers
        for cm_info in caps.get("context_managers", []):
            name = cm_info.get("name", "")
            if name:
                self._context_manager_to_service[name] = service_key

        # Providers
        for prov_info in caps.get("providers", []):
            name = prov_info.get("name", "")
            if name:
                self._provider_to_service[name] = service_key

        # Content
        content_info = caps.get("content", {})
        self._content_by_service[service_key] = content_info.get("paths", [])

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_tool_service(self, tool_name: str) -> str | None:
        """Return the service key owning *tool_name*, or None."""
        return self._tool_to_service.get(tool_name)

    def get_hook_services(self, event: str) -> list[dict[str, Any]]:
        """Return hook entries for *event*, sorted by priority (ascending).

        Each entry is a dict with keys: service_key, hook_name, event, priority.
        """
        matching = [e for e in self._hook_entries if e["event"] == event]
        matching.sort(key=lambda e: e["priority"])
        return matching

    def get_orchestrator_service(self, name: str) -> str | None:
        """Return the service key owning orchestrator *name*, or None."""
        return self._orchestrator_to_service.get(name)

    def get_context_manager_service(self, name: str) -> str | None:
        """Return the service key owning context manager *name*, or None."""
        return self._context_manager_to_service.get(name)

    def get_provider_service(self, name: str) -> str | None:
        """Return the service key owning provider *name*, or None."""
        return self._provider_to_service.get(name)

    def get_content_services(self) -> dict[str, list[str]]:
        """Return mapping of service_key -> list of content paths."""
        return dict(self._content_by_service)

    def get_all_tool_specs(self) -> list[dict[str, Any]]:
        """Return aggregated tool specs from all services."""
        return list(self._all_tool_specs)

    def get_all_hook_descriptors(self) -> list[dict[str, Any]]:
        """Return aggregated hook descriptors from all services."""
        return list(self._all_hook_descriptors)
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_registry.py -v
```
Expected: All 11 tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && git add -A && git commit -m "feat: capability registry from service describe responses"
```

---

### Task 5: Message Router

**Files:**
- Create: `amplifier-ipc-host/src/amplifier_ipc_host/router.py`
- Create: `amplifier-ipc-host/tests/test_router.py`

**Step 1: Write the failing tests**

Create `amplifier-ipc-host/tests/test_router.py`:

```python
"""Tests for the message router and hook fan-out logic."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from amplifier_ipc_host.registry import CapabilityRegistry
from amplifier_ipc_host.router import Router


# ---------------------------------------------------------------------------
# Helpers — mock services with a fake client
# ---------------------------------------------------------------------------


class FakeClient:
    """Mock client that records requests and returns canned responses."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self._responses = responses or {}
        self.requests: list[tuple[str, Any]] = []

    async def request(self, method: str, params: Any = None) -> Any:
        self.requests.append((method, params))
        if method in self._responses:
            return self._responses[method]
        return {"ok": True}


class FakeService:
    """Minimal stand-in for ServiceProcess with a FakeClient."""

    def __init__(self, name: str, responses: dict[str, Any] | None = None) -> None:
        self.name = name
        self.client = FakeClient(responses)


def _build_router_with_two_services() -> tuple[Router, FakeService, FakeService]:
    """Build a Router with foundation (tools, hooks) and providers services."""
    foundation = FakeService("foundation", responses={
        "tool.execute": {"success": True, "output": "hello from bash"},
        "hook.emit": {"action": "CONTINUE"},
    })
    providers = FakeService("providers", responses={
        "provider.complete": {"content": "I am Claude", "tool_calls": None},
    })

    registry = CapabilityRegistry()
    registry.register("foundation", {
        "name": "amplifier_foundation",
        "capabilities": {
            "tools": [{"name": "bash", "description": "shell", "input_schema": {}}],
            "hooks": [{"name": "approval", "events": ["tool:pre"], "priority": 10}],
            "orchestrators": [],
            "context_managers": [{"name": "simple"}],
            "providers": [],
            "content": {"paths": []},
        },
    })
    registry.register("providers", {
        "name": "amplifier_providers",
        "capabilities": {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [{"name": "anthropic"}],
            "content": {"paths": []},
        },
    })

    services = {"foundation": foundation, "providers": providers}
    router = Router(
        registry=registry,
        services=services,
        context_manager_key="foundation",
        provider_key="providers",
    )
    return router, foundation, providers


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_tool_execute() -> None:
    """request.tool_execute routes to the service that owns the tool."""
    router, foundation, _ = _build_router_with_two_services()

    result = await router.route_request(
        "request.tool_execute",
        {"name": "bash", "input": {"command": "echo hi"}},
    )

    assert result == {"success": True, "output": "hello from bash"}
    assert len(foundation.client.requests) == 1
    assert foundation.client.requests[0][0] == "tool.execute"


@pytest.mark.asyncio
async def test_route_tool_execute_unknown_tool() -> None:
    """request.tool_execute for unknown tool raises an error."""
    router, _, _ = _build_router_with_two_services()

    from amplifier_ipc_protocol.errors import JsonRpcError

    with pytest.raises(JsonRpcError, match="Unknown tool"):
        await router.route_request(
            "request.tool_execute",
            {"name": "nonexistent_tool", "input": {}},
        )


@pytest.mark.asyncio
async def test_route_hook_emit() -> None:
    """request.hook_emit fans out to all hook services for the event."""
    router, foundation, _ = _build_router_with_two_services()

    result = await router.route_request(
        "request.hook_emit",
        {"event": "tool:pre", "data": {"tool_name": "bash"}},
    )

    assert result["action"] == "CONTINUE"
    # Foundation's hook.emit was called
    hook_calls = [(m, p) for m, p in foundation.client.requests if m == "hook.emit"]
    assert len(hook_calls) == 1


@pytest.mark.asyncio
async def test_route_hook_emit_no_hooks() -> None:
    """request.hook_emit with no registered hooks returns CONTINUE."""
    router, _, _ = _build_router_with_two_services()

    result = await router.route_request(
        "request.hook_emit",
        {"event": "unknown:event", "data": {}},
    )

    assert result["action"] == "CONTINUE"


@pytest.mark.asyncio
async def test_route_context_add_message() -> None:
    """request.context_add_message routes to the context manager service."""
    router, foundation, _ = _build_router_with_two_services()

    result = await router.route_request(
        "request.context_add_message",
        {"message": {"role": "user", "content": "hello"}},
    )

    assert result == {"ok": True}
    ctx_calls = [(m, p) for m, p in foundation.client.requests if m == "context.add_message"]
    assert len(ctx_calls) == 1


@pytest.mark.asyncio
async def test_route_context_get_messages() -> None:
    """request.context_get_messages routes to the context manager service."""
    router, foundation, _ = _build_router_with_two_services()
    foundation.client._responses["context.get_messages"] = {"messages": []}

    result = await router.route_request(
        "request.context_get_messages",
        {"provider_info": {}},
    )

    assert result == {"messages": []}


@pytest.mark.asyncio
async def test_route_context_clear() -> None:
    """request.context_clear routes to the context manager service."""
    router, foundation, _ = _build_router_with_two_services()

    result = await router.route_request("request.context_clear", None)

    assert result == {"ok": True}
    ctx_calls = [(m, p) for m, p in foundation.client.requests if m == "context.clear"]
    assert len(ctx_calls) == 1


@pytest.mark.asyncio
async def test_route_provider_complete() -> None:
    """request.provider_complete routes to the provider service."""
    router, _, providers = _build_router_with_two_services()

    result = await router.route_request(
        "request.provider_complete",
        {"request": {"messages": [], "tools": []}},
    )

    assert result["content"] == "I am Claude"
    assert len(providers.client.requests) == 1
    assert providers.client.requests[0][0] == "provider.complete"


@pytest.mark.asyncio
async def test_route_unknown_method() -> None:
    """Unknown method raises JsonRpcError."""
    router, _, _ = _build_router_with_two_services()

    from amplifier_ipc_protocol.errors import JsonRpcError

    with pytest.raises(JsonRpcError, match="Unknown routing method"):
        await router.route_request("request.unknown_method", {})


@pytest.mark.asyncio
async def test_hook_fanout_deny_short_circuits() -> None:
    """DENY from a hook short-circuits — later hooks are not called."""
    # Two services both have hooks for the same event
    svc_a = FakeService("svc_a", responses={
        "hook.emit": {"action": "DENY", "reason": "blocked"},
    })
    svc_b = FakeService("svc_b", responses={
        "hook.emit": {"action": "CONTINUE"},
    })

    registry = CapabilityRegistry()
    registry.register("svc_a", {
        "name": "svc_a", "capabilities": {
            "tools": [], "hooks": [{"name": "blocker", "events": ["tool:pre"], "priority": 1}],
            "orchestrators": [], "context_managers": [], "providers": [], "content": {"paths": []},
        },
    })
    registry.register("svc_b", {
        "name": "svc_b", "capabilities": {
            "tools": [], "hooks": [{"name": "logger", "events": ["tool:pre"], "priority": 100}],
            "orchestrators": [], "context_managers": [], "providers": [], "content": {"paths": []},
        },
    })

    router = Router(
        registry=registry,
        services={"svc_a": svc_a, "svc_b": svc_b},
        context_manager_key="svc_a",
        provider_key="svc_a",
    )

    result = await router.route_request(
        "request.hook_emit",
        {"event": "tool:pre", "data": {}},
    )

    assert result["action"] == "DENY"
    # svc_b should NOT have been called
    assert len(svc_b.client.requests) == 0
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_router.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_host.router'`

**Step 3: Write the implementation**

Create `amplifier-ipc-host/src/amplifier_ipc_host/router.py`:

```python
"""Message router for amplifier-ipc-host.

Routes orchestrator requests (``request.*``) to the appropriate services
using the capability registry. Implements hook fan-out with priority
ordering and short-circuit on DENY/ASK_USER.
"""

from __future__ import annotations

import logging
from typing import Any

from amplifier_ipc_protocol.errors import INVALID_PARAMS, METHOD_NOT_FOUND, JsonRpcError

from amplifier_ipc_host.registry import CapabilityRegistry

logger = logging.getLogger(__name__)


class Router:
    """Routes orchestrator requests to services based on the capability registry.

    Args:
        registry: The capability registry (from describe responses).
        services: Mapping of service_key -> service object (must have .client attribute).
        context_manager_key: Service key for the active context manager.
        provider_key: Service key for the active provider.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        services: dict[str, Any],
        context_manager_key: str,
        provider_key: str,
    ) -> None:
        self._registry = registry
        self._services = services
        self._context_manager_key = context_manager_key
        self._provider_key = provider_key

    async def route_request(self, method: str, params: Any) -> Any:
        """Route an orchestrator request to the appropriate service.

        Args:
            method: The JSON-RPC method (e.g. "request.tool_execute").
            params: The request parameters.

        Returns:
            The result from the target service.

        Raises:
            JsonRpcError: If the method is unknown or the target is not found.
        """
        if method == "request.tool_execute":
            return await self._route_tool_execute(params or {})
        if method == "request.hook_emit":
            return await self._route_hook_emit(params or {})
        if method == "request.context_add_message":
            return await self._route_to_context_manager("context.add_message", params)
        if method == "request.context_get_messages":
            return await self._route_to_context_manager("context.get_messages", params)
        if method == "request.context_clear":
            return await self._route_to_context_manager("context.clear", params)
        if method == "request.provider_complete":
            return await self._route_to_provider(params)

        raise JsonRpcError(METHOD_NOT_FOUND, f"Unknown routing method: {method!r}")

    # ------------------------------------------------------------------
    # Tool routing
    # ------------------------------------------------------------------

    async def _route_tool_execute(self, params: dict[str, Any]) -> Any:
        """Route tool.execute to the service owning the named tool."""
        tool_name = params.get("name", "")
        service_key = self._registry.get_tool_service(tool_name)

        if service_key is None:
            raise JsonRpcError(INVALID_PARAMS, f"Unknown tool: {tool_name!r}")

        service = self._services[service_key]
        return await service.client.request("tool.execute", params)

    # ------------------------------------------------------------------
    # Hook fan-out
    # ------------------------------------------------------------------

    async def _route_hook_emit(self, params: dict[str, Any]) -> Any:
        """Fan out hook.emit to all services registered for the event.

        Hooks are called in priority order (ascending). DENY and ASK_USER
        short-circuit the chain. MODIFY updates the data for subsequent hooks.
        """
        event = params.get("event", "")
        data = dict(params.get("data") or {})

        hook_entries = self._registry.get_hook_services(event)

        if not hook_entries:
            return {"action": "CONTINUE"}

        final_result: dict[str, Any] = {"action": "CONTINUE"}

        # Group consecutive entries by service_key to batch per-service calls
        # But we need to respect priority order, so call one service at a time
        for entry in hook_entries:
            service_key = entry["service_key"]
            service = self._services.get(service_key)
            if service is None:
                continue

            result = await service.client.request(
                "hook.emit",
                {"event": event, "data": data},
            )

            final_result = result
            action = result.get("action", "CONTINUE")

            if action in ("DENY", "ASK_USER"):
                break

            if action == "MODIFY" and isinstance(result.get("data"), dict):
                data.update(result["data"])

        return final_result

    # ------------------------------------------------------------------
    # Context manager routing
    # ------------------------------------------------------------------

    async def _route_to_context_manager(self, method: str, params: Any) -> Any:
        """Route a context.* method to the context manager service."""
        service = self._services[self._context_manager_key]
        return await service.client.request(method, params)

    # ------------------------------------------------------------------
    # Provider routing
    # ------------------------------------------------------------------

    async def _route_to_provider(self, params: Any) -> Any:
        """Route provider.complete to the provider service."""
        service = self._services[self._provider_key]
        return await service.client.request("provider.complete", params)
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_router.py -v
```
Expected: All 11 tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && git add -A && git commit -m "feat: message router with hook fan-out and short-circuit"
```

---

### Task 6: Content Resolution

**Files:**
- Create: `amplifier-ipc-host/src/amplifier_ipc_host/content.py`
- Create: `amplifier-ipc-host/tests/test_content.py`

**Step 1: Write the failing tests**

Create `amplifier-ipc-host/tests/test_content.py`:

```python
"""Tests for content resolution and system prompt assembly."""

from __future__ import annotations

from typing import Any

import pytest

from amplifier_ipc_host.content import assemble_system_prompt, resolve_mention
from amplifier_ipc_host.registry import CapabilityRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeClient:
    """Mock client returning canned content.read responses."""

    def __init__(self, content_map: dict[str, str]) -> None:
        self._content_map = content_map

    async def request(self, method: str, params: Any = None) -> Any:
        if method == "content.read":
            path = (params or {}).get("path", "")
            if path in self._content_map:
                return {"content": self._content_map[path]}
            raise Exception(f"Content not found: {path}")
        return {}


class FakeService:
    def __init__(self, name: str, content_map: dict[str, str]) -> None:
        self.name = name
        self.client = FakeClient(content_map)


def _build_registry_and_services() -> tuple[
    CapabilityRegistry, dict[str, FakeService]
]:
    foundation = FakeService("foundation", {
        "agents/explorer.md": "# Explorer Agent\nYou are an explorer.",
        "context/shared/common.md": "Common context content.",
    })
    superpowers = FakeService("superpowers", {
        "context/philosophy.md": "Superpowers philosophy.",
    })

    registry = CapabilityRegistry()
    registry.register("foundation", {
        "name": "amplifier_foundation",
        "capabilities": {
            "tools": [], "hooks": [], "orchestrators": [], "context_managers": [],
            "providers": [],
            "content": {"paths": ["agents/explorer.md", "context/shared/common.md"]},
        },
    })
    registry.register("superpowers", {
        "name": "amplifier_superpowers",
        "capabilities": {
            "tools": [], "hooks": [], "orchestrators": [], "context_managers": [],
            "providers": [],
            "content": {"paths": ["context/philosophy.md"]},
        },
    })

    services = {"foundation": foundation, "superpowers": superpowers}
    return registry, services


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_mention_simple() -> None:
    """Resolves @foundation:agents/explorer.md to content."""
    registry, services = _build_registry_and_services()

    content = await resolve_mention("foundation:agents/explorer.md", registry, services)

    assert content == "# Explorer Agent\nYou are an explorer."


@pytest.mark.asyncio
async def test_resolve_mention_unknown_service() -> None:
    """Raises ValueError for an unknown service namespace."""
    registry, services = _build_registry_and_services()

    with pytest.raises(ValueError, match="Unknown content namespace"):
        await resolve_mention("nonexistent:agents/foo.md", registry, services)


@pytest.mark.asyncio
async def test_resolve_mention_no_colon() -> None:
    """Raises ValueError for a mention missing the colon separator."""
    registry, services = _build_registry_and_services()

    with pytest.raises(ValueError, match="Invalid mention format"):
        await resolve_mention("no-colon-here", registry, services)


@pytest.mark.asyncio
async def test_assemble_system_prompt_gathers_context() -> None:
    """assemble_system_prompt gathers context files from all services."""
    registry, services = _build_registry_and_services()

    prompt = await assemble_system_prompt(registry, services)

    assert "Common context content." in prompt
    assert "Superpowers philosophy." in prompt


@pytest.mark.asyncio
async def test_assemble_system_prompt_with_mentions() -> None:
    """assemble_system_prompt resolves @mentions and includes them."""
    registry, services = _build_registry_and_services()

    prompt = await assemble_system_prompt(
        registry,
        services,
        mentions=["foundation:agents/explorer.md"],
    )

    assert "Explorer Agent" in prompt


@pytest.mark.asyncio
async def test_assemble_system_prompt_deduplicates() -> None:
    """Identical content from context and mention is deduplicated."""
    registry, services = _build_registry_and_services()

    prompt = await assemble_system_prompt(
        registry,
        services,
        # This is already included as a context file
        mentions=["foundation:context/shared/common.md"],
    )

    # Should only appear once
    assert prompt.count("Common context content.") == 1
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_content.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_host.content'`

**Step 3: Write the implementation**

Create `amplifier-ipc-host/src/amplifier_ipc_host/content.py`:

```python
"""Content resolution and system prompt assembly for amplifier-ipc-host.

Resolves ``@namespace:path`` mentions by calling ``content.read`` on services
and assembles context files into a deduplicated system prompt.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from amplifier_ipc_host.registry import CapabilityRegistry

logger = logging.getLogger(__name__)


async def resolve_mention(
    mention: str,
    registry: CapabilityRegistry,
    services: dict[str, Any],
) -> str:
    """Resolve a ``namespace:path`` mention to its file content.

    Strips a leading ``@`` if present. Finds the service that owns the
    namespace via the registry's content_services mapping, then calls
    ``content.read`` on that service.

    Args:
        mention: A mention string like ``"foundation:agents/explorer.md"``
            or ``"@foundation:agents/explorer.md"``.
        registry: The capability registry.
        services: Service key -> service object mapping.

    Returns:
        The file content as a string.

    Raises:
        ValueError: If the mention format is invalid or the namespace is unknown.
    """
    # Strip leading @
    mention = mention.lstrip("@")

    if ":" not in mention:
        raise ValueError(f"Invalid mention format (expected 'namespace:path'): {mention!r}")

    namespace, path = mention.split(":", 1)

    content_map = registry.get_content_services()
    if namespace not in content_map:
        raise ValueError(f"Unknown content namespace: {namespace!r}")

    service = services[namespace]
    result = await service.client.request("content.read", {"path": path})
    return result["content"]


async def assemble_system_prompt(
    registry: CapabilityRegistry,
    services: dict[str, Any],
    *,
    mentions: list[str] | None = None,
) -> str:
    """Assemble a system prompt from service content files.

    Gathers all ``context/`` files from all services, resolves any extra
    ``@mentions``, and deduplicates by SHA-256.

    Args:
        registry: The capability registry.
        services: Service key -> service object mapping.
        mentions: Optional extra ``namespace:path`` mentions to resolve and include.

    Returns:
        The assembled system prompt string.
    """
    parts: list[str] = []
    seen_hashes: set[str] = set()

    def _sha256(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def _add_if_new(key: str, content: str) -> None:
        h = _sha256(content)
        if h not in seen_hashes:
            seen_hashes.add(h)
            parts.append(f'<context_file path="{key}">\n{content}\n</context_file>')

    # 1. Gather context files from all services
    content_map = registry.get_content_services()
    for service_key, content_paths in content_map.items():
        service = services.get(service_key)
        if service is None:
            continue
        for path in content_paths:
            # Only include context/ files in the system prompt by default
            if not path.startswith("context/"):
                continue
            try:
                result = await service.client.request("content.read", {"path": path})
                _add_if_new(f"{service_key}:{path}", result["content"])
            except Exception:
                logger.warning(
                    "Failed to read content %s from service %s",
                    path, service_key, exc_info=True,
                )

    # 2. Resolve extra @mentions
    if mentions:
        for mention in mentions:
            try:
                content = await resolve_mention(mention, registry, services)
                _add_if_new(mention.lstrip("@"), content)
            except (ValueError, Exception):
                logger.warning(
                    "Could not resolve mention %r — skipping",
                    mention, exc_info=True,
                )

    return "\n".join(parts)
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_content.py -v
```
Expected: All 6 tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && git add -A && git commit -m "feat: content resolution and system prompt assembly"
```

---

### Task 7: Session Persistence

**Files:**
- Create: `amplifier-ipc-host/src/amplifier_ipc_host/persistence.py`
- Create: `amplifier-ipc-host/tests/test_persistence.py`

**Step 1: Write the failing tests**

Create `amplifier-ipc-host/tests/test_persistence.py`:

```python
"""Tests for session transcript persistence."""

from __future__ import annotations

import json
from pathlib import Path

from amplifier_ipc_host.persistence import SessionPersistence


def test_creates_session_directory(tmp_path: Path) -> None:
    """SessionPersistence creates the session directory on init."""
    persistence = SessionPersistence("session-001", tmp_path)

    session_dir = tmp_path / "session-001"
    assert session_dir.is_dir()


def test_append_message_creates_transcript(tmp_path: Path) -> None:
    """First append_message creates transcript.jsonl with the message."""
    persistence = SessionPersistence("session-001", tmp_path)

    persistence.append_message({"role": "user", "content": "hello"})

    transcript_path = tmp_path / "session-001" / "transcript.jsonl"
    assert transcript_path.exists()
    lines = transcript_path.read_text().strip().split("\n")
    assert len(lines) == 1
    msg = json.loads(lines[0])
    assert msg["role"] == "user"
    assert msg["content"] == "hello"


def test_append_multiple_messages(tmp_path: Path) -> None:
    """Multiple append_message calls produce multiple JSONL lines."""
    persistence = SessionPersistence("session-001", tmp_path)

    persistence.append_message({"role": "user", "content": "hello"})
    persistence.append_message({"role": "assistant", "content": "hi"})
    persistence.append_message({"role": "user", "content": "how are you"})

    transcript_path = tmp_path / "session-001" / "transcript.jsonl"
    lines = transcript_path.read_text().strip().split("\n")
    assert len(lines) == 3
    assert json.loads(lines[0])["role"] == "user"
    assert json.loads(lines[1])["role"] == "assistant"
    assert json.loads(lines[2])["content"] == "how are you"


def test_save_metadata(tmp_path: Path) -> None:
    """save_metadata writes metadata.json."""
    persistence = SessionPersistence("session-001", tmp_path)

    persistence.save_metadata({"session_id": "session-001", "model": "claude"})

    metadata_path = tmp_path / "session-001" / "metadata.json"
    assert metadata_path.exists()
    meta = json.loads(metadata_path.read_text())
    assert meta["session_id"] == "session-001"
    assert meta["model"] == "claude"


def test_finalize(tmp_path: Path) -> None:
    """finalize writes updated metadata with status=completed."""
    persistence = SessionPersistence("session-001", tmp_path)
    persistence.save_metadata({"session_id": "session-001"})

    persistence.finalize()

    metadata_path = tmp_path / "session-001" / "metadata.json"
    meta = json.loads(metadata_path.read_text())
    assert meta["status"] == "completed"


def test_load_transcript(tmp_path: Path) -> None:
    """load_transcript returns all appended messages."""
    persistence = SessionPersistence("session-001", tmp_path)
    persistence.append_message({"role": "user", "content": "a"})
    persistence.append_message({"role": "assistant", "content": "b"})

    messages = persistence.load_transcript()

    assert len(messages) == 2
    assert messages[0]["content"] == "a"
    assert messages[1]["content"] == "b"


def test_load_transcript_empty(tmp_path: Path) -> None:
    """load_transcript returns empty list when no messages exist."""
    persistence = SessionPersistence("session-001", tmp_path)

    messages = persistence.load_transcript()

    assert messages == []
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_persistence.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_host.persistence'`

**Step 3: Write the implementation**

Create `amplifier-ipc-host/src/amplifier_ipc_host/persistence.py`:

```python
"""Session transcript persistence for amplifier-ipc-host.

Append-only JSONL transcript with metadata. Simple and crash-safe.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionPersistence:
    """Append-only session transcript and metadata persistence.

    Storage layout:
        ``<base_dir>/<session_id>/transcript.jsonl`` — one message per line
        ``<base_dir>/<session_id>/metadata.json`` — session metadata

    Args:
        session_id: Unique session identifier.
        base_dir: Root directory for session storage.
    """

    def __init__(self, session_id: str, base_dir: Path) -> None:
        self._session_id = session_id
        self._session_dir = base_dir / session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._transcript_path = self._session_dir / "transcript.jsonl"
        self._metadata_path = self._session_dir / "metadata.json"

    def append_message(self, message: dict[str, Any]) -> None:
        """Append a message to the transcript JSONL file.

        Opens the file in append mode so each call adds one line.

        Args:
            message: A dict representing the message to persist.
        """
        line = json.dumps(message, separators=(",", ":")) + "\n"
        with open(self._transcript_path, "a", encoding="utf-8") as f:
            f.write(line)

    def save_metadata(self, metadata: dict[str, Any]) -> None:
        """Write (overwrite) metadata.json with the given metadata.

        Args:
            metadata: The metadata dict to persist.
        """
        with open(self._metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

    def finalize(self) -> None:
        """Mark the session as completed in metadata.

        Loads existing metadata, sets ``status`` to ``"completed"``, writes it back.
        """
        metadata: dict[str, Any] = {}
        if self._metadata_path.exists():
            with open(self._metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)

        metadata["status"] = "completed"
        self.save_metadata(metadata)

    def load_transcript(self) -> list[dict[str, Any]]:
        """Load all messages from the transcript file.

        Returns:
            List of message dicts. Empty list if the file doesn't exist.
        """
        if not self._transcript_path.exists():
            return []

        messages: list[dict[str, Any]] = []
        with open(self._transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    messages.append(json.loads(line))
        return messages
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_persistence.py -v
```
Expected: All 7 tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && git add -A && git commit -m "feat: session transcript persistence (append-only JSONL)"
```

---

### Task 8: Host Orchestration

**Files:**
- Create: `amplifier-ipc-host/src/amplifier_ipc_host/host.py`
- Create: `amplifier-ipc-host/tests/test_host.py`

This is the main class. It ties config, lifecycle, registry, router, content, and persistence together. We test it with in-process fakes — real subprocess integration comes in Task 10.

**Step 1: Write the failing tests**

Create `amplifier-ipc-host/tests/test_host.py`:

```python
"""Tests for the Host class orchestration logic."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from amplifier_ipc_host.config import HostSettings, SessionConfig
from amplifier_ipc_host.host import Host


# ---------------------------------------------------------------------------
# Helpers — mock services
# ---------------------------------------------------------------------------


class FakeClient:
    """Records requests, returns canned responses keyed by method."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.requests: list[tuple[str, Any]] = []

    async def request(self, method: str, params: Any = None) -> Any:
        self.requests.append((method, params))
        if method in self._responses:
            resp = self._responses[method]
            if callable(resp):
                return resp(params)
            return resp
        return {"ok": True}

    async def send_notification(self, method: str, params: Any = None) -> None:
        pass


class FakeService:
    def __init__(self, name: str, responses: dict[str, Any]) -> None:
        self.name = name
        self.client = FakeClient(responses)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_host_build_registry(tmp_path: Path) -> None:
    """Host._build_registry sends describe to each service and populates registry."""
    foundation = FakeService("foundation", {
        "describe": {
            "name": "foundation",
            "capabilities": {
                "tools": [{"name": "bash", "description": "shell", "input_schema": {}}],
                "hooks": [],
                "orchestrators": [{"name": "streaming"}],
                "context_managers": [{"name": "simple"}],
                "providers": [],
                "content": {"paths": []},
            },
        },
    })
    providers = FakeService("providers", {
        "describe": {
            "name": "providers",
            "capabilities": {
                "tools": [],
                "hooks": [],
                "orchestrators": [],
                "context_managers": [],
                "providers": [{"name": "anthropic"}],
                "content": {"paths": []},
            },
        },
    })

    config = SessionConfig(
        services=["foundation", "providers"],
        orchestrator="streaming",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()

    host = Host(config, settings, session_dir=tmp_path)
    host._services = {"foundation": foundation, "providers": providers}

    await host._build_registry()

    assert host._registry.get_tool_service("bash") == "foundation"
    assert host._registry.get_orchestrator_service("streaming") == "foundation"
    assert host._registry.get_provider_service("anthropic") == "providers"


@pytest.mark.asyncio
async def test_host_route_orchestrator_message(tmp_path: Path) -> None:
    """Host routes a request.tool_execute message from the orchestrator."""
    config = SessionConfig(
        services=["foundation"],
        orchestrator="streaming",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()
    host = Host(config, settings, session_dir=tmp_path)

    foundation = FakeService("foundation", {
        "tool.execute": {"success": True, "output": "hello"},
    })
    host._services = {"foundation": foundation}

    # Manually set up the registry and router
    from amplifier_ipc_host.registry import CapabilityRegistry
    from amplifier_ipc_host.router import Router

    host._registry = CapabilityRegistry()
    host._registry.register("foundation", {
        "name": "foundation",
        "capabilities": {
            "tools": [{"name": "bash", "description": "shell", "input_schema": {}}],
            "hooks": [], "orchestrators": [{"name": "streaming"}],
            "context_managers": [{"name": "simple"}],
            "providers": [{"name": "anthropic"}],
            "content": {"paths": []},
        },
    })
    host._router = Router(
        registry=host._registry,
        services=host._services,
        context_manager_key="foundation",
        provider_key="foundation",
    )

    result = await host._handle_orchestrator_request(
        "request.tool_execute",
        {"name": "bash", "input": {"command": "echo hi"}},
    )

    assert result == {"success": True, "output": "hello"}
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_host.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_host.host'`

**Step 3: Write the implementation**

Create `amplifier-ipc-host/src/amplifier_ipc_host/host.py`:

```python
"""Main Host class — ties config, lifecycle, registry, router, content, persistence together.

The Host is the central orchestrator for amplifier-ipc. It:
1. Spawns all service processes
2. Discovers capabilities (describe)
3. Assembles the system prompt from content
4. Sends orchestrator.execute
5. Routes orchestrator requests to services
6. Relays streaming notifications to stdout
7. Persists messages
8. Tears down services on completion
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from amplifier_ipc_protocol.errors import JsonRpcError, make_error_response
from amplifier_ipc_protocol.framing import read_message, write_message

from amplifier_ipc_host.config import HostSettings, SessionConfig, resolve_service_command
from amplifier_ipc_host.content import assemble_system_prompt
from amplifier_ipc_host.lifecycle import ServiceProcess, shutdown_service, spawn_service
from amplifier_ipc_host.persistence import SessionPersistence
from amplifier_ipc_host.registry import CapabilityRegistry
from amplifier_ipc_host.router import Router

logger = logging.getLogger(__name__)


class Host:
    """Central message bus for amplifier-ipc.

    Args:
        config: Parsed session configuration.
        settings: Host settings (service overrides, etc.).
        session_dir: Base directory for session persistence.
    """

    def __init__(
        self,
        config: SessionConfig,
        settings: HostSettings,
        *,
        session_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._settings = settings
        self._session_dir = session_dir or Path.home() / ".amplifier" / "sessions"
        self._services: dict[str, Any] = {}
        self._registry: CapabilityRegistry = CapabilityRegistry()
        self._router: Router | None = None
        self._persistence: SessionPersistence | None = None

    async def run(self, prompt: str) -> str:
        """Run a full turn: spawn, discover, route, teardown.

        Args:
            prompt: The user's prompt text.

        Returns:
            The orchestrator's final response text.
        """
        session_id = str(uuid.uuid4().hex[:16])
        self._persistence = SessionPersistence(session_id, self._session_dir)

        try:
            # 1. Spawn all services
            await self._spawn_services()

            # 2. Discover capabilities
            await self._build_registry()

            # 3. Build router
            orchestrator_key = self._registry.get_orchestrator_service(
                self._config.orchestrator
            )
            context_manager_key = self._registry.get_context_manager_service(
                self._config.context_manager
            )
            provider_key = self._registry.get_provider_service(self._config.provider)

            if orchestrator_key is None:
                raise RuntimeError(
                    f"Orchestrator {self._config.orchestrator!r} not found in any service"
                )
            if context_manager_key is None:
                raise RuntimeError(
                    f"Context manager {self._config.context_manager!r} not found"
                )
            if provider_key is None:
                raise RuntimeError(
                    f"Provider {self._config.provider!r} not found in any service"
                )

            self._router = Router(
                registry=self._registry,
                services=self._services,
                context_manager_key=context_manager_key,
                provider_key=provider_key,
            )

            # 4. Assemble system prompt
            system_prompt = await assemble_system_prompt(
                self._registry, self._services
            )

            # 5. Send orchestrator.execute
            orchestrator_service = self._services[orchestrator_key]
            orchestrator_config = self._config.component_config.get(
                self._config.orchestrator, {}
            )

            execute_params = {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "tools": self._registry.get_all_tool_specs(),
                "hooks": self._registry.get_all_hook_descriptors(),
                "config": orchestrator_config,
            }

            # 6. Enter bidirectional routing loop with the orchestrator
            response = await self._orchestrator_loop(
                orchestrator_service, execute_params
            )

            # 7. Finalize persistence
            self._persistence.save_metadata({
                "session_id": session_id,
                "orchestrator": self._config.orchestrator,
                "provider": self._config.provider,
            })
            self._persistence.finalize()

            return response

        finally:
            # 8. Teardown all services
            await self._teardown_services()

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    async def _spawn_services(self) -> None:
        """Spawn all service processes from the session config."""
        for service_name in self._config.services:
            command, cwd = resolve_service_command(service_name, self._settings)
            svc = await spawn_service(service_name, command, working_dir=cwd)
            self._services[service_name] = svc

    async def _build_registry(self) -> None:
        """Send describe to each service and populate the registry."""
        self._registry = CapabilityRegistry()
        for service_key, service in self._services.items():
            try:
                result = await asyncio.wait_for(
                    service.client.request("describe"), timeout=10.0
                )
                self._registry.register(service_key, result)
            except Exception:
                logger.error(
                    "Failed to describe service %s", service_key, exc_info=True
                )

    async def _orchestrator_loop(
        self,
        orchestrator_service: Any,
        execute_params: dict[str, Any],
    ) -> str:
        """Run the bidirectional routing loop with the orchestrator.

        Sends orchestrator.execute, then reads messages from the orchestrator:
        - request.* → route via Router, send response back
        - stream.* → relay to host stdout
        - Final response (matching execute id) → return result
        """
        assert self._router is not None

        client = orchestrator_service.client

        # Send orchestrator.execute as a request
        # We manually write the request and read responses to handle bidirectional comms
        execute_id = "_orch_execute_1"
        execute_msg = {
            "jsonrpc": "2.0",
            "id": execute_id,
            "method": "orchestrator.execute",
            "params": execute_params,
        }

        process = orchestrator_service.process
        assert process.stdin is not None
        assert process.stdout is not None

        await write_message(process.stdin, execute_msg)

        # Read loop: handle orchestrator messages until we get the final response
        while True:
            message = await read_message(process.stdout)

            if message is None:
                raise ConnectionError("Orchestrator closed connection before responding")

            msg_id = message.get("id")

            # Final response to our orchestrator.execute
            if msg_id == execute_id and ("result" in message or "error" in message):
                if "error" in message:
                    err = message["error"]
                    raise RuntimeError(
                        f"Orchestrator error: {err.get('message', 'unknown')}"
                    )
                return message.get("result", "")

            # Request from orchestrator (has method and id)
            if "method" in message and msg_id is not None:
                method = message["method"]
                params = message.get("params")

                # Persist tool results flowing through
                if self._persistence and method == "request.context_add_message":
                    msg_data = (params or {}).get("message")
                    if msg_data:
                        self._persistence.append_message(msg_data)

                try:
                    result = await self._router.route_request(method, params)
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": result,
                    }
                except JsonRpcError as exc:
                    response = exc.to_response(msg_id)
                except Exception as exc:
                    response = make_error_response(msg_id, -32603, str(exc))

                await write_message(process.stdin, response)
                continue

            # Notification from orchestrator (has method, no id)
            if "method" in message and msg_id is None:
                # Relay streaming notifications to host stdout
                sys.stdout.write(json.dumps(message) + "\n")
                sys.stdout.flush()
                continue

    async def _handle_orchestrator_request(
        self, method: str, params: Any
    ) -> Any:
        """Handle a single orchestrator request (for testing).

        Args:
            method: The JSON-RPC method.
            params: The request parameters.

        Returns:
            The routing result.
        """
        assert self._router is not None
        return await self._router.route_request(method, params)

    async def _teardown_services(self) -> None:
        """Shut down all spawned services."""
        for service in self._services.values():
            if isinstance(service, ServiceProcess):
                try:
                    await shutdown_service(service, timeout=3.0)
                except Exception:
                    logger.warning(
                        "Error shutting down %s", service.name, exc_info=True
                    )
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_host.py -v
```
Expected: All 2 tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && git add -A && git commit -m "feat: Host class with orchestrator routing loop"
```

---

### Task 9: CLI Entry Point

**Files:**
- Create: `amplifier-ipc-host/src/amplifier_ipc_host/__main__.py`

**Step 1: Write the implementation**

Create `amplifier-ipc-host/src/amplifier_ipc_host/__main__.py`:

```python
"""CLI entry point for amplifier-ipc-host.

Usage:
    amplifier-ipc-host run session.yaml
    python -m amplifier_ipc_host run session.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from amplifier_ipc_host.config import HostSettings, load_settings, parse_session_config
from amplifier_ipc_host.host import Host


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="amplifier-ipc-host",
        description="Amplifier IPC Host — central message bus for IPC services",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a session")
    run_parser.add_argument(
        "session_config",
        type=Path,
        help="Path to the session YAML config file",
    )
    run_parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Prompt text (reads from stdin if not provided)",
    )

    args = parser.parse_args()

    if args.command == "run":
        _run_session(args.session_config, args.prompt)


def _run_session(config_path: Path, prompt: str | None) -> None:
    """Parse config, load settings, create Host, run prompt."""
    config = parse_session_config(config_path)

    settings = load_settings(
        user_settings_path=Path.home() / ".amplifier" / "settings.yaml",
        project_settings_path=Path(".amplifier") / "settings.yaml",
    )

    host = Host(config, settings)

    if prompt is None:
        print("Enter prompt (Ctrl+D to send):", file=sys.stderr)
        prompt = sys.stdin.read().strip()

    if not prompt:
        print("Error: empty prompt", file=sys.stderr)
        sys.exit(1)

    response = asyncio.run(host.run(prompt))
    print(response)


if __name__ == "__main__":
    main()
```

**Step 2: Verify CLI parses correctly**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m amplifier_ipc_host --help
```
Expected: Shows help text with "run" subcommand.

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m amplifier_ipc_host run --help
```
Expected: Shows help for the run subcommand with session_config and --prompt arguments.

**Step 3: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && git add -A && git commit -m "feat: CLI entry point (amplifier-ipc-host run session.yaml)"
```

---

### Task 10: Integration Test + Public Exports

**Files:**
- Modify: `amplifier-ipc-host/src/amplifier_ipc_host/__init__.py`
- Create: `amplifier-ipc-host/tests/test_integration.py`

This task creates a real end-to-end test: a tiny mock service (using `amplifier-ipc-protocol`'s `Server`) is spawned as a subprocess, and the Host discovers it, routes through it, and tears it down. We also finalize the public `__init__.py` exports.

**Step 1: Write the failing test**

Create `amplifier-ipc-host/tests/test_integration.py`:

```python
"""Integration tests: Host spawns real mock services and routes messages.

Creates a minimal mock service package on disk, spawns it as a subprocess,
and verifies the full discover → route → teardown cycle.
"""

from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path

import pytest

from amplifier_ipc_host.config import HostSettings, SessionConfig
from amplifier_ipc_host.lifecycle import ServiceProcess, shutdown_service, spawn_service
from amplifier_ipc_host.registry import CapabilityRegistry


# ---------------------------------------------------------------------------
# Helpers — create a mock service on disk
# ---------------------------------------------------------------------------


def _create_mock_service_package(tmp_path: Path) -> Path:
    """Create a minimal service package that has one tool and content.

    Returns the path to the package directory (parent of the package).
    """
    pkg_dir = tmp_path / "mock_service"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")

    # A tool
    tools_dir = pkg_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "echo.py").write_text(textwrap.dedent("""\
        from amplifier_ipc_protocol.decorators import tool
        from amplifier_ipc_protocol.models import ToolResult

        @tool
        class EchoTool:
            name = "echo"
            description = "Echoes the input back"
            input_schema = {"type": "object", "properties": {"text": {"type": "string"}}}

            async def execute(self, input):
                return ToolResult(success=True, output=input.get("text", ""))
    """))

    # Content
    agents_dir = pkg_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "test_agent.md").write_text("# Test Agent")

    context_dir = pkg_dir / "context"
    context_dir.mkdir()
    (context_dir / "test_context.md").write_text("Test context content.")

    # Entry point script — runs the Server
    (pkg_dir / "__main__.py").write_text(textwrap.dedent("""\
        from amplifier_ipc_protocol.server import Server
        Server("mock_service").run()
    """))

    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_describe_and_teardown(tmp_path: Path) -> None:
    """Spawn a real mock service, send describe, verify capabilities, teardown."""
    pkg_parent = _create_mock_service_package(tmp_path)

    # Build PYTHONPATH so the subprocess can find both the mock package and the protocol lib
    protocol_src = str(Path(__file__).resolve().parents[2] / "amplifier-ipc-protocol" / "src")
    extra_paths = f"{pkg_parent}:{protocol_src}"

    import os
    env = {**os.environ, "PYTHONPATH": extra_paths}

    # Spawn using python -m mock_service
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "mock_service",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(pkg_parent),
        env=env,
    )

    from amplifier_ipc_protocol.client import Client

    client = Client(process.stdout, process.stdin)
    svc = ServiceProcess(name="mock_service", process=process, client=client)

    try:
        # Send describe
        result = await asyncio.wait_for(client.request("describe"), timeout=10.0)

        assert result["name"] == "mock_service"
        caps = result["capabilities"]

        # Verify tool was discovered
        tool_names = [t["name"] for t in caps["tools"]]
        assert "echo" in tool_names

        # Verify content was discovered
        content_paths = caps["content"]["paths"]
        assert "agents/test_agent.md" in content_paths
        assert "context/test_context.md" in content_paths

        # Execute the tool
        tool_result = await asyncio.wait_for(
            client.request("tool.execute", {"name": "echo", "input": {"text": "hello"}}),
            timeout=5.0,
        )
        assert tool_result["success"] is True
        assert tool_result["output"] == "hello"

        # Read content
        content_result = await asyncio.wait_for(
            client.request("content.read", {"path": "context/test_context.md"}),
            timeout=5.0,
        )
        assert content_result["content"] == "Test context content."

    finally:
        await shutdown_service(svc, timeout=3.0)

    assert process.returncode is not None


@pytest.mark.asyncio
async def test_registry_from_real_service(tmp_path: Path) -> None:
    """Build a CapabilityRegistry from a real service's describe response."""
    pkg_parent = _create_mock_service_package(tmp_path)
    protocol_src = str(Path(__file__).resolve().parents[2] / "amplifier-ipc-protocol" / "src")
    extra_paths = f"{pkg_parent}:{protocol_src}"

    import os
    env = {**os.environ, "PYTHONPATH": extra_paths}

    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "mock_service",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(pkg_parent),
        env=env,
    )

    from amplifier_ipc_protocol.client import Client

    client = Client(process.stdout, process.stdin)
    svc = ServiceProcess(name="mock_service", process=process, client=client)

    try:
        result = await asyncio.wait_for(client.request("describe"), timeout=10.0)

        registry = CapabilityRegistry()
        registry.register("mock", result)

        assert registry.get_tool_service("echo") == "mock"
        specs = registry.get_all_tool_specs()
        assert any(s["name"] == "echo" for s in specs)

        content = registry.get_content_services()
        assert "agents/test_agent.md" in content["mock"]

    finally:
        await shutdown_service(svc, timeout=3.0)
```

**Step 2: Update __init__.py with public exports**

Update `amplifier-ipc-host/src/amplifier_ipc_host/__init__.py`:

```python
"""amplifier-ipc-host: Central message bus for Amplifier IPC services."""

from amplifier_ipc_host.config import (
    HostSettings,
    ServiceOverride,
    SessionConfig,
    load_settings,
    parse_session_config,
    resolve_service_command,
)
from amplifier_ipc_host.content import assemble_system_prompt, resolve_mention
from amplifier_ipc_host.host import Host
from amplifier_ipc_host.lifecycle import ServiceProcess, shutdown_service, spawn_service
from amplifier_ipc_host.persistence import SessionPersistence
from amplifier_ipc_host.registry import CapabilityRegistry
from amplifier_ipc_host.router import Router

__all__ = [
    # Core
    "Host",
    # Config
    "SessionConfig",
    "HostSettings",
    "ServiceOverride",
    "parse_session_config",
    "load_settings",
    "resolve_service_command",
    # Lifecycle
    "ServiceProcess",
    "spawn_service",
    "shutdown_service",
    # Registry
    "CapabilityRegistry",
    # Router
    "Router",
    # Content
    "resolve_mention",
    "assemble_system_prompt",
    # Persistence
    "SessionPersistence",
]
```

**Step 3: Run integration tests**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_integration.py -v --timeout=30
```
Expected: Both integration tests PASS.

**Step 4: Run ALL tests to confirm nothing is broken**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/ -v
```
Expected: All tests across all test files PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && git add -A && git commit -m "feat: integration tests and public API exports"
```

---

## Summary

| Task | What it builds | Test file | Key exports |
|------|---------------|-----------|-------------|
| 1 | Project scaffolding | — | — |
| 2 | Config parsing | `test_config.py` | `SessionConfig`, `HostSettings`, `parse_session_config`, `load_settings`, `resolve_service_command` |
| 3 | Service lifecycle | `test_lifecycle.py` | `ServiceProcess`, `spawn_service`, `shutdown_service` |
| 4 | Capability registry | `test_registry.py` | `CapabilityRegistry` |
| 5 | Message router | `test_router.py` | `Router` |
| 6 | Content resolution | `test_content.py` | `resolve_mention`, `assemble_system_prompt` |
| 7 | Session persistence | `test_persistence.py` | `SessionPersistence` |
| 8 | Host orchestration | `test_host.py` | `Host` |
| 9 | CLI entry point | (manual verify) | `amplifier-ipc-host run` |
| 10 | Integration + exports | `test_integration.py` | Full `__init__.py` |