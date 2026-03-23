# Pydantic Migration Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Convert all 20 dataclasses to Pydantic BaseModel and use pydantic-settings for config loading.

**Architecture:** Every `@dataclass` in `src/amplifier_ipc/` becomes a Pydantic `BaseModel` (or `BaseSettings` for `HostSettings`). The protocol layer already uses Pydantic v2 (`src/amplifier_ipc/protocol/models.py`) — this extends that pattern to definitions, config, events, lifecycle, and spawner models. `pydantic-settings` is added as a new dependency so `HostSettings` can support env var overrides.

**Tech Stack:** Pydantic v2 (existing), pydantic-settings v2 (new), PyYAML (existing)

---

## Codebase Orientation

**Existing Pydantic pattern** (follow this style — see `src/amplifier_ipc/protocol/models.py`):
```python
from pydantic import BaseModel, ConfigDict, Field

class ToolCall(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    id: str
    name: str = Field(default="", ...)
    arguments: dict[str, Any] = Field(default_factory=dict)
```

**Key conventions:**
- `from __future__ import annotations` is used in all files
- `ConfigDict` for model configuration (not inner `class Config`)
- `Field(default_factory=...)` for mutable defaults
- pytest with `tmp_path` fixtures, `pytest-asyncio` with `asyncio_mode = "auto"`

**Run tests:** `uv run pytest tests/ -v`
**Run subset:** `uv run pytest tests/host/test_definitions.py -v`
**Run linting:** `uv run ruff check src/`

---

### Task 1: Add pydantic-settings Dependency

**Files:**
- Modify: `pyproject.toml:9-12`

**Step 1: Add pydantic-settings to dependencies**

In `pyproject.toml`, change the `dependencies` list from:

```toml
dependencies = [
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "click>=8.1.0",
    "rich>=13.0.0",
    "prompt-toolkit>=3.0.52",
]
```

to:

```toml
dependencies = [
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0",
    "click>=8.1.0",
    "rich>=13.0.0",
    "prompt-toolkit>=3.0.52",
]
```

**Step 2: Install the new dependency**

Run: `uv sync`
Expected: Resolves and installs `pydantic-settings`. No errors.

**Step 3: Verify the import works**

Run: `uv run python -c "from pydantic_settings import BaseSettings; print('OK')"`
Expected: Prints `OK`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add pydantic-settings dependency"
```

---

### Task 2: Convert Definition Models (definitions.py)

**Files:**
- Modify: `src/amplifier_ipc/host/definitions.py:1-93`

This file has 4 dataclasses: `ServiceEntry`, `AgentDefinition`, `BehaviorDefinition`, `ResolvedAgent`. The parsing functions (`parse_agent_definition`, `parse_behavior_definition`, `resolve_agent`) and helpers (`_to_bool`, `_to_behavior_list`, `_parse_service`) remain unchanged — they construct models via keyword args which works identically with Pydantic.

**Step 1: Replace imports and convert all 4 dataclasses**

Replace the import block and all 4 dataclass definitions. Change:

```python
import asyncio
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
```

to:

```python
import asyncio
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
```

Then replace each dataclass. Change `ServiceEntry`:

```python
@dataclass
class ServiceEntry:
    """Represents the service block from a definition file."""

    stack: str | None = None
    source: str | None = None
    command: str | None = None
```

to:

```python
class ServiceEntry(BaseModel):
    """Represents the service block from a definition file."""

    stack: str | None = None
    source: str | None = None
    command: str | None = None
```

Change `AgentDefinition`:

```python
@dataclass
class AgentDefinition:
    """Parsed representation of an agent definition YAML file."""

    ref: str | None = None
    uuid: str | None = None
    version: str | None = None
    description: str | None = None
    orchestrator: str | None = None
    context_manager: str | None = None
    provider: str | None = None
    tools: bool = False
    hooks: bool = False
    agents: bool = False
    context: bool = False
    behaviors: list[dict[str, str]] = field(default_factory=list)
    service: ServiceEntry | None = None
    component_config: dict[str, Any] = field(default_factory=dict)
```

to:

```python
class AgentDefinition(BaseModel):
    """Parsed representation of an agent definition YAML file."""

    ref: str | None = None
    uuid: str | None = None
    version: str | None = None
    description: str | None = None
    orchestrator: str | None = None
    context_manager: str | None = None
    provider: str | None = None
    tools: bool = False
    hooks: bool = False
    agents: bool = False
    context: bool = False
    behaviors: list[dict[str, str]] = Field(default_factory=list)
    service: ServiceEntry | None = None
    component_config: dict[str, Any] = Field(default_factory=dict)
```

Change `BehaviorDefinition`:

```python
@dataclass
class BehaviorDefinition:
    """Parsed representation of a behavior definition YAML file."""

    ref: str | None = None
    uuid: str | None = None
    version: str | None = None
    description: str | None = None
    tools: bool = False
    hooks: bool = False
    context: bool = False
    behaviors: list[dict[str, str]] = field(default_factory=list)
    service: ServiceEntry | None = None
    component_config: dict[str, Any] = field(default_factory=dict)
```

to:

```python
class BehaviorDefinition(BaseModel):
    """Parsed representation of a behavior definition YAML file."""

    ref: str | None = None
    uuid: str | None = None
    version: str | None = None
    description: str | None = None
    tools: bool = False
    hooks: bool = False
    context: bool = False
    behaviors: list[dict[str, str]] = Field(default_factory=list)
    service: ServiceEntry | None = None
    component_config: dict[str, Any] = Field(default_factory=dict)
```

Change `ResolvedAgent`:

```python
@dataclass
class ResolvedAgent:
    """Resolved agent configuration after merging behaviors into an agent definition."""

    services: list[tuple[str, ServiceEntry]] = field(default_factory=list)
    service_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    definition_ids: dict[str, str] = field(default_factory=dict)
    orchestrator: str | None = None
    context_manager: str | None = None
    provider: str | None = None
    component_config: dict[str, Any] = field(default_factory=dict)
```

to:

```python
class ResolvedAgent(BaseModel):
    """Resolved agent configuration after merging behaviors into an agent definition."""

    services: list[tuple[str, ServiceEntry]] = Field(default_factory=list)
    service_configs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    definition_ids: dict[str, str] = Field(default_factory=dict)
    orchestrator: str | None = None
    context_manager: str | None = None
    provider: str | None = None
    component_config: dict[str, Any] = Field(default_factory=dict)
```

**Step 2: Run definition tests to verify**

Run: `uv run pytest tests/host/test_definitions.py tests/host/test_definition_files.py tests/host/test_definition_registry.py -v`
Expected: All tests PASS. The constructors use keyword args which work identically. The `hasattr` checks in `test_agent_definition_has_ref_not_local_ref` and `test_behavior_definition_has_ref_not_local_ref` still pass because Pydantic models don't expose undefined fields.

**Step 3: Run downstream tests that import definition models**

Run: `uv run pytest tests/cli/test_session_launcher.py tests/cli/test_definitions.py -v`
Expected: All tests PASS.

**Step 4: Commit**

```bash
git add src/amplifier_ipc/host/definitions.py
git commit -m "refactor: convert definition models to Pydantic BaseModel"
```

---

### Task 3: Convert Config Models (config.py)

**Files:**
- Modify: `src/amplifier_ipc/host/config.py:1-41`

This file has 3 dataclasses: `ServiceOverride`, `HostSettings`, `SessionConfig`. The functions `parse_session_config`, `load_settings`, and `resolve_service_command` remain unchanged — they construct models via keyword args.

`HostSettings` becomes a `BaseSettings` subclass so it automatically supports env var overrides (e.g., `AMPLIFIER_IPC__SERVICE_OVERRIDES`). The `load_settings()` factory function stays as-is — it handles the complex two-file YAML merging and agent-name scoping, then constructs a validated `HostSettings` instance.

**Step 1: Replace imports and convert all 3 classes**

Change the import block:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
```

to:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
```

Change `ServiceOverride`:

```python
@dataclass
class ServiceOverride:
    """Command and working directory override for a named service."""

    command: list[str] = field(default_factory=list)
    working_dir: str | None = None
```

to:

```python
class ServiceOverride(BaseModel):
    """Command and working directory override for a named service."""

    command: list[str] = Field(default_factory=list)
    working_dir: str | None = None
```

Change `HostSettings`:

```python
@dataclass
class HostSettings:
    """Host-level settings loaded from user/project YAML settings files."""

    service_overrides: dict[str, ServiceOverride] = field(default_factory=dict)
```

to:

```python
class HostSettings(BaseSettings):
    """Host-level settings loaded from user/project YAML settings files.

    Extends BaseSettings so environment variables with the ``AMPLIFIER_IPC_``
    prefix are automatically picked up (e.g. for CI/container overrides).
    The ``load_settings()`` factory handles YAML file loading.
    """

    model_config = SettingsConfigDict(
        env_prefix="AMPLIFIER_IPC_",
        env_nested_delimiter="__",
    )

    service_overrides: dict[str, ServiceOverride] = Field(default_factory=dict)
```

Change `SessionConfig`:

```python
@dataclass
class SessionConfig:
    """Parsed representation of a session YAML configuration file."""

    services: list[str]
    orchestrator: str
    context_manager: str
    provider: str
    component_config: dict[str, dict[str, Any]] = field(default_factory=dict)
```

to:

```python
class SessionConfig(BaseModel):
    """Parsed representation of a session YAML configuration file."""

    services: list[str]
    orchestrator: str
    context_manager: str
    provider: str
    component_config: dict[str, dict[str, Any]] = Field(default_factory=dict)
```

Also update the section comment from `# Dataclasses` to `# Models`.

**Step 2: Run config tests to verify**

Run: `uv run pytest tests/host/test_config.py -v`
Expected: All tests PASS. `HostSettings()` with no args works (BaseSettings supports it). `HostSettings(service_overrides={...})` also works. `load_settings()` returns a validated `HostSettings`.

**Step 3: Run downstream tests**

Run: `uv run pytest tests/host/test_host.py tests/cli/test_session_launcher.py tests/cli/test_session_spawner.py -v`
Expected: All tests PASS.

**Step 4: Commit**

```bash
git add src/amplifier_ipc/host/config.py
git commit -m "refactor: convert config models to Pydantic, HostSettings to BaseSettings"
```

---

### Task 4: Convert Event Models (events.py)

**Files:**
- Modify: `src/amplifier_ipc/host/events.py`

This file has 9 dataclasses: `HostEvent` (base) and 8 subclasses. These are simple value objects with no mutable defaults (except `ApprovalRequestEvent.params`). Pydantic supports model inheritance, so `isinstance(event, HostEvent)` still works.

**Step 1: Replace the entire file contents**

Change from:

```python
"""Host event dataclass hierarchy.

Events are yielded by :meth:`Host.run` and :meth:`Host._orchestrator_loop`
as an async stream, replacing the previous batch-result return value.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HostEvent:
    """Base class for all host events."""


@dataclass
class StreamTokenEvent(HostEvent):
    """Emitted when the orchestrator streams a text token (stream.token)."""

    token: str = ""


@dataclass
class StreamThinkingEvent(HostEvent):
    """Emitted when the orchestrator streams a thinking fragment (stream.thinking)."""

    thinking: str = ""


@dataclass
class StreamToolCallStartEvent(HostEvent):
    """Emitted when the orchestrator starts a tool call (stream.tool_call_start)."""

    tool_name: str = ""


@dataclass
class StreamContentBlockStartEvent(HostEvent):
    """Emitted when the provider starts a new content block (stream.content_block_start)."""

    block_type: str = ""
    index: int = 0


@dataclass
class StreamContentBlockEndEvent(HostEvent):
    """Emitted when the provider ends a content block (stream.content_block_end)."""

    block_type: str = ""
    index: int = 0


@dataclass
class ApprovalRequestEvent(HostEvent):
    """Emitted when the orchestrator requests user approval (approval_request)."""

    params: dict = field(default_factory=dict)  # type: ignore[type-arg]


@dataclass
class ErrorEvent(HostEvent):
    """Emitted when the orchestrator sends a non-fatal error notification (error)."""

    message: str = ""


@dataclass
class CompleteEvent(HostEvent):
    """Emitted as the final event carrying the orchestrator's full response (complete)."""

    result: str = ""
```

to:

```python
"""Host event model hierarchy.

Events are yielded by :meth:`Host.run` and :meth:`Host._orchestrator_loop`
as an async stream, replacing the previous batch-result return value.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HostEvent(BaseModel):
    """Base class for all host events."""


class StreamTokenEvent(HostEvent):
    """Emitted when the orchestrator streams a text token (stream.token)."""

    token: str = ""


class StreamThinkingEvent(HostEvent):
    """Emitted when the orchestrator streams a thinking fragment (stream.thinking)."""

    thinking: str = ""


class StreamToolCallStartEvent(HostEvent):
    """Emitted when the orchestrator starts a tool call (stream.tool_call_start)."""

    tool_name: str = ""


class StreamContentBlockStartEvent(HostEvent):
    """Emitted when the provider starts a new content block (stream.content_block_start)."""

    block_type: str = ""
    index: int = 0


class StreamContentBlockEndEvent(HostEvent):
    """Emitted when the provider ends a content block (stream.content_block_end)."""

    block_type: str = ""
    index: int = 0


class ApprovalRequestEvent(HostEvent):
    """Emitted when the orchestrator requests user approval (approval_request)."""

    params: dict[str, Any] = Field(default_factory=dict)


class ErrorEvent(HostEvent):
    """Emitted when the orchestrator sends a non-fatal error notification (error)."""

    message: str = ""


class CompleteEvent(HostEvent):
    """Emitted as the final event carrying the orchestrator's full response (complete)."""

    result: str = ""
```

Note: `ApprovalRequestEvent.params` is now properly typed as `dict[str, Any]` (removing the `# type: ignore`), and `Field(default_factory=dict)` replaces `field(default_factory=dict)`.

**Step 2: Run event tests**

Run: `uv run pytest tests/host/test_events.py -v`
Expected: All tests PASS. `isinstance(event, HostEvent)` checks pass because Pydantic supports model inheritance.

**Step 3: Run downstream tests that use events**

Run: `uv run pytest tests/host/test_host.py tests/host/test_spawner.py tests/cli/test_streaming.py -v`
Expected: All tests PASS.

**Step 4: Commit**

```bash
git add src/amplifier_ipc/host/events.py
git commit -m "refactor: convert event models to Pydantic BaseModel"
```

---

### Task 5: Convert Lifecycle Model (lifecycle.py)

**Files:**
- Modify: `src/amplifier_ipc/host/lifecycle.py:1-21`

This file has 1 dataclass: `ServiceProcess`. It holds `asyncio.subprocess.Process` and `Client` — non-serializable types that require `arbitrary_types_allowed=True`.

**Step 1: Replace import and convert the dataclass**

Change:

```python
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from amplifier_ipc.protocol.client import Client
```

to:

```python
from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, ConfigDict

from amplifier_ipc.protocol.client import Client
```

Change the class:

```python
@dataclass
class ServiceProcess:
    """A running service subprocess with an attached JSON-RPC client."""

    name: str
    process: asyncio.subprocess.Process
    client: Client
```

to:

```python
class ServiceProcess(BaseModel):
    """A running service subprocess with an attached JSON-RPC client."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    process: asyncio.subprocess.Process
    client: Client
```

**Step 2: Run lifecycle tests**

Run: `uv run pytest tests/host/test_lifecycle.py -v`
Expected: All tests PASS. `spawn_service()` constructs `ServiceProcess(name=..., process=..., client=...)` with keyword args — compatible.

**Step 3: Commit**

```bash
git add src/amplifier_ipc/host/lifecycle.py
git commit -m "refactor: convert ServiceProcess to Pydantic BaseModel"
```

---

### Task 6: Convert Spawner Model (spawner.py)

**Files:**
- Modify: `src/amplifier_ipc/host/spawner.py:1-12,261-299`

This file has 1 dataclass: `SpawnRequest` (at line 261). The rest of the file is utility functions that stay unchanged.

**Step 1: Replace import and convert the dataclass**

Change the imports at the top of the file:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4
```

to:

```python
from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
```

Change the class (around line 261):

```python
@dataclass
class SpawnRequest:
    """Parameters for spawning a child session.

    Attributes:
        agent:                Agent identifier to spawn (``'self'`` clones the
                              parent config; any other value is a named agent).
        instruction:          The instruction to pass to the child session.
        context_depth:        How much parent context to include: ``'none'``,
                              ``'recent'``, or ``'all'``.
        context_scope:        Which messages to include: ``'conversation'``
                              keeps only user/assistant turns; any other value
                              keeps all messages.
        context_turns:        Number of recent turns to include when
                              *context_depth* is ``'recent'``.
        exclude_tools:        Tool names to remove from the child config
                              (blocklist mode).
        inherit_tools:        Tool names to keep in the child config
                              (allowlist mode).
        exclude_hooks:        Hook names to remove from the child config.
        inherit_hooks:        Hook names to keep in the child config.
        agents:               Agent bundle(s) to make available in the child
                              session.
        provider_preferences: Ordered provider/model preference list.
        model_role:           Override the child agent's default model role.
    """

    agent: str
    instruction: str
    context_depth: str = "none"
    context_scope: str = "conversation"
    context_turns: int | None = None
    exclude_tools: list[str] | None = None
    inherit_tools: list[str] | None = None
    exclude_hooks: list[str] | None = None
    inherit_hooks: list[str] | None = None
    agents: str | list[str] | None = None
    provider_preferences: list[dict[str, Any]] | None = None
    model_role: str | None = None
```

to:

```python
class SpawnRequest(BaseModel):
    """Parameters for spawning a child session.

    Attributes:
        agent:                Agent identifier to spawn (``'self'`` clones the
                              parent config; any other value is a named agent).
        instruction:          The instruction to pass to the child session.
        context_depth:        How much parent context to include: ``'none'``,
                              ``'recent'``, or ``'all'``.
        context_scope:        Which messages to include: ``'conversation'``
                              keeps only user/assistant turns; any other value
                              keeps all messages.
        context_turns:        Number of recent turns to include when
                              *context_depth* is ``'recent'``.
        exclude_tools:        Tool names to remove from the child config
                              (blocklist mode).
        inherit_tools:        Tool names to keep in the child config
                              (allowlist mode).
        exclude_hooks:        Hook names to remove from the child config.
        inherit_hooks:        Hook names to keep in the child config.
        agents:               Agent bundle(s) to make available in the child
                              session.
        provider_preferences: Ordered provider/model preference list.
        model_role:           Override the child agent's default model role.
    """

    agent: str
    instruction: str
    context_depth: str = "none"
    context_scope: str = "conversation"
    context_turns: int | None = None
    exclude_tools: list[str] | None = None
    inherit_tools: list[str] | None = None
    exclude_hooks: list[str] | None = None
    inherit_hooks: list[str] | None = None
    agents: str | list[str] | None = None
    provider_preferences: list[dict[str, Any]] | None = None
    model_role: str | None = None
```

**Step 2: Run spawner tests**

Run: `uv run pytest tests/host/test_spawner.py -v`
Expected: All tests PASS.

**Step 3: Commit**

```bash
git add src/amplifier_ipc/host/spawner.py
git commit -m "refactor: convert SpawnRequest (host) to Pydantic BaseModel"
```

---

### Task 7: Convert CLI Settings Model (settings.py)

**Files:**
- Modify: `src/amplifier_ipc/cli/settings.py:1-51`

This file has 1 dataclass: `SettingsPaths` (line 33). `AppSettings` is a regular class (not a dataclass) — it stays unchanged.

**Step 1: Replace import and convert SettingsPaths**

Change the imports:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
```

to:

```python
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel
```

Change the class:

```python
@dataclass
class SettingsPaths:
    """Holds file paths for all three settings scopes."""

    global_path: Path
    project_path: Path
    local_path: Path

    @classmethod
    def default(cls) -> SettingsPaths:
        """Return default paths for all three scopes based on current environment."""
        home = Path.home()
        cwd = Path.cwd()
        return cls(
            global_path=home / _AMPLIFIER_DIR / _SETTINGS_FILENAME,
            project_path=cwd / _AMPLIFIER_DIR / _SETTINGS_FILENAME,
            local_path=cwd / _AMPLIFIER_DIR / _LOCAL_SETTINGS_FILENAME,
        )
```

to:

```python
class SettingsPaths(BaseModel):
    """Holds file paths for all three settings scopes."""

    global_path: Path
    project_path: Path
    local_path: Path

    @classmethod
    def default(cls) -> SettingsPaths:
        """Return default paths for all three scopes based on current environment."""
        home = Path.home()
        cwd = Path.cwd()
        return cls(
            global_path=home / _AMPLIFIER_DIR / _SETTINGS_FILENAME,
            project_path=cwd / _AMPLIFIER_DIR / _SETTINGS_FILENAME,
            local_path=cwd / _AMPLIFIER_DIR / _LOCAL_SETTINGS_FILENAME,
        )
```

Also update the section comment from `# SettingsPaths dataclass` to `# SettingsPaths model`.

**Step 2: Run tests that exercise settings**

Run: `uv run pytest tests/cli/test_lifecycle.py tests/cli/test_copy_imports.py -v`
Expected: All tests PASS. `SettingsPaths.default()` uses `cls(...)` which works identically with Pydantic. `AppSettings.__init__` takes a `SettingsPaths` argument — Pydantic model instances are valid Python objects.

**Step 3: Commit**

```bash
git add src/amplifier_ipc/cli/settings.py
git commit -m "refactor: convert SettingsPaths to Pydantic BaseModel"
```

---

### Task 8: Convert CLI Session Spawner Model (session_spawner.py)

**Files:**
- Modify: `src/amplifier_ipc/cli/session_spawner.py:1-38`

This file has 1 dataclass: `SpawnRequest` (different from `host/spawner.py`'s `SpawnRequest`).

**Step 1: Replace import and convert the dataclass**

Change the imports:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from amplifier_ipc.host.config import HostSettings, SessionConfig
from amplifier_ipc.host.host import Host
```

to:

```python
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from amplifier_ipc.host.config import HostSettings, SessionConfig
from amplifier_ipc.host.host import Host
```

Change the class:

```python
@dataclass
class SpawnRequest:
    """Request to spawn a child agent sub-session.

    Attributes:
        agent_name: The local_ref alias of the child agent to spawn.
        instruction: The instruction/prompt to run in the child session.
        parent_session_id: The session ID of the parent (orchestrator) session.
        context_settings: Optional context propagation settings.
    """

    agent_name: str
    instruction: str
    parent_session_id: str
    context_settings: dict[str, Any] = field(default_factory=dict)
```

to:

```python
class SpawnRequest(BaseModel):
    """Request to spawn a child agent sub-session.

    Attributes:
        agent_name: The local_ref alias of the child agent to spawn.
        instruction: The instruction/prompt to run in the child session.
        parent_session_id: The session ID of the parent (orchestrator) session.
        context_settings: Optional context propagation settings.
    """

    agent_name: str
    instruction: str
    parent_session_id: str
    context_settings: dict[str, Any] = Field(default_factory=dict)
```

Also update the section comment from `# Dataclasses` to `# Models`.

**Step 2: Run session spawner tests**

Run: `uv run pytest tests/cli/test_session_spawner.py -v`
Expected: All tests PASS.

**Step 3: Commit**

```bash
git add src/amplifier_ipc/cli/session_spawner.py
git commit -m "refactor: convert SpawnRequest (CLI) to Pydantic BaseModel"
```

---

### Task 9: Verify No Remaining Dataclasses

> **SPEC REVIEW WARNING:** The automated spec review loop exhausted its maximum 3 iterations before converging on this task. The final (3rd) iteration verdict was **APPROVED** with all 5 checklist items passing, but earlier iterations had issues that required re-verification. Human reviewer should independently confirm:
> 1. No `@dataclass` or `from dataclasses import` in `src/amplifier_ipc/`
> 2. Full test suite passes (764 passed, 1 skipped as of last run — exceeds the 746 baseline)
> 3. `ruff check src/amplifier_ipc/` is clean
>
> The approved verdict text is preserved below for reference.
>
> <details>
> <summary>Final spec review verdict (iteration 3/3)</summary>
>
> - [x] Step 1 — No `@dataclass` in `src/amplifier_ipc/`: grep returned no matches (exit 1). PASS
> - [x] Step 2 — No `from dataclasses import` in `src/amplifier_ipc/`: grep returned no matches (exit 1). PASS
> - [x] Step 3 — Full test suite passes: 764 passed, 1 skipped in 6.14s. PASS
> - [x] Step 4 — `ruff check` clean: "All checks passed!" PASS
> - [x] Acceptance criterion — 20 dataclasses converted, 1 new dependency added: Confirmed by absence of `@dataclass` in source. PASS
>
> No extra changes found. Verdict: APPROVED.
> </details>

**Step 1: Search for any remaining `@dataclass` decorators in source**

Run: `grep -rn "@dataclass" src/amplifier_ipc/`
Expected: **No matches.** Every `@dataclass` should have been converted. If any remain, go back and convert them following the same pattern.

**Step 2: Search for any remaining `from dataclasses import` in source**

Run: `grep -rn "from dataclasses import" src/amplifier_ipc/`
Expected: **No matches.** All dataclass imports should have been replaced.

**Step 3: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: All 746 tests PASS with no errors.

If any tests fail, the most likely causes are:

1. **Positional argument construction** — Pydantic v2 models don't accept positional args by default. Fix: Use keyword args. (All existing tests already use keyword args, so this is unlikely.)

2. **Extra keyword arguments** — Pydantic rejects unknown fields by default. Fix: Add `model_config = ConfigDict(extra="ignore")` to the affected model, or fix the caller.

3. **Type coercion differences** — Pydantic validates types strictly. A test passing `command="string"` to a field typed `list[str]` would fail. Fix: Pass the correct type.

4. **BaseSettings env var interference** — If an environment variable like `AMPLIFIER_IPC_SERVICE_OVERRIDES` happens to be set, `HostSettings()` would pick it up. Fix: Clear the env var in the test environment, or mock `os.environ`.

**Step 4: Run linting**

Run: `uv run ruff check src/amplifier_ipc/`
Expected: No new warnings. If `ruff` flags unused imports (e.g., `dataclass` or `field` left behind), remove them.

**Step 5: Final commit (if any fixes were needed)**

```bash
git add -A
git commit -m "refactor: complete Pydantic migration - fix test adjustments"
```

---

## Summary of Changes

| File | Dataclasses Converted | Target |
|---|---|---|
| `src/amplifier_ipc/host/definitions.py` | `ServiceEntry`, `AgentDefinition`, `BehaviorDefinition`, `ResolvedAgent` | `BaseModel` |
| `src/amplifier_ipc/host/config.py` | `ServiceOverride`, `SessionConfig` | `BaseModel` |
| `src/amplifier_ipc/host/config.py` | `HostSettings` | `BaseSettings` |
| `src/amplifier_ipc/host/events.py` | `HostEvent`, `StreamTokenEvent`, `StreamThinkingEvent`, `StreamToolCallStartEvent`, `StreamContentBlockStartEvent`, `StreamContentBlockEndEvent`, `ApprovalRequestEvent`, `ErrorEvent`, `CompleteEvent` | `BaseModel` |
| `src/amplifier_ipc/host/lifecycle.py` | `ServiceProcess` | `BaseModel` (with `arbitrary_types_allowed`) |
| `src/amplifier_ipc/host/spawner.py` | `SpawnRequest` | `BaseModel` |
| `src/amplifier_ipc/cli/settings.py` | `SettingsPaths` | `BaseModel` |
| `src/amplifier_ipc/cli/session_spawner.py` | `SpawnRequest` | `BaseModel` |
| `pyproject.toml` | — | Add `pydantic-settings>=2.0` |

**Total: 20 dataclasses converted, 1 new dependency added.**

## What Did NOT Change

- **`src/amplifier_ipc/protocol/models.py`** — Already Pydantic. Untouched.
- **`src/amplifier_ipc/cli/settings.py:AppSettings`** — This is a regular class (not a dataclass). It manages multi-scope YAML settings with deep-merge, read, and write operations. Converting it to `BaseSettings` would require significant redesign of its read/write lifecycle and is a separate task.
- **All function signatures** — `parse_agent_definition()`, `load_settings()`, `parse_session_config()`, etc. all return the same types and accept the same arguments.
- **`__init__.py` re-exports** — All public names stay the same.
- **Test files** — No test changes expected (all constructors use keyword args, all `isinstance` checks work with Pydantic inheritance).
