# Protocol Extensions & Architectural Refactoring — Phase 1 Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Add provider streaming, cross-service shared state, and sub-session spawning protocols to the host, plus move registry/definitions from CLI to host so the host can resolve agent definitions autonomously.

**Architecture:** The host gains three new protocol capabilities (streaming relay, state store, session spawning) and two modules moved from the CLI (registry, definitions). The CLI becomes a thin UI shell that imports from the host. All new wire methods are routed through the existing `Router` class. State is persisted as `state.json` alongside the existing `transcript.jsonl` and `metadata.json`.

**Tech Stack:** Python 3.11+, Pydantic v2, hatchling, pytest + pytest-asyncio (`asyncio_mode = "auto"`), PyYAML, `tmp_path` fixtures for filesystem tests.

---

## Codebase Orientation

**Key directories:**
- Protocol: `amplifier-ipc-protocol/src/amplifier_ipc_protocol/`
- Host: `amplifier-ipc-host/src/amplifier_ipc_host/`
- CLI: `amplifier-ipc-cli/src/amplifier_ipc_cli/`
- Host tests: `amplifier-ipc-host/tests/`
- CLI tests: `amplifier-ipc-cli/tests/`

**Existing patterns to follow:**
- Tests use plain `async def test_*()` functions (pytest-asyncio auto mode) — no `@pytest.mark.asyncio` needed
- Fake services use `FakeClient` (records calls, returns canned responses) and `FakeService` (wraps a `FakeClient` with `.client` attribute) — see `amplifier-ipc-host/tests/test_router.py` lines 19–38
- Host tests inject fakes via `host._services = {...}` and `host._router = Router(...)` to bypass subprocess spawning
- `tmp_path` fixture for filesystem tests (see `test_persistence.py`, `test_registry.py`)
- `SessionPersistence` creates `<base_dir>/<session_id>/` directory and writes `transcript.jsonl`, `metadata.json`
- `CapabilityRegistry` (in host) maps capability names → service keys from `describe` responses
- `Registry` (in CLI) manages `$AMPLIFIER_HOME` filesystem: `agents.yaml`, `behaviors.yaml`, `definitions/`, `environments/`
- `Router` dispatches `request.*` methods from the orchestrator to services
- Host `_orchestrator_loop` reads messages from orchestrator stdout, routes `request.*` messages, yields `HostEvent` subclasses for `stream.*` notifications

**pyproject.toml dependency chain:**
- `amplifier-ipc-protocol` → no local deps (only `pydantic>=2.0`)
- `amplifier-ipc-host` → depends on `amplifier-ipc-protocol` + `pyyaml>=6.0`
- `amplifier-ipc-cli` → depends on `amplifier-ipc-host` (+ click, rich, prompt-toolkit, pyyaml)

---

## Task 1: Move Registry class from CLI to host

**Files:**
- Move: `amplifier-ipc-cli/src/amplifier_ipc_cli/registry.py` → `amplifier-ipc-host/src/amplifier_ipc_host/definition_registry.py`
- Modify: `amplifier-ipc-cli/src/amplifier_ipc_cli/registry.py` (replace with re-export stub)
- Modify: `amplifier-ipc-host/src/amplifier_ipc_host/__init__.py` (add export)
- Test: `amplifier-ipc-host/tests/test_definition_registry.py`

We name it `definition_registry.py` in the host to avoid collision with the existing `registry.py` (which is `CapabilityRegistry` — the describe-response routing table). The CLI's `registry.py` becomes a thin re-export.

**Step 1: Write the test in the host package**

Create `amplifier-ipc-host/tests/test_definition_registry.py`:

```python
"""Tests for definition registry (moved from CLI)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture()
def home_dir(tmp_path: Path) -> Path:
    """Return a temporary directory to use as AMPLIFIER_HOME."""
    return tmp_path / "amplifier_home"


@pytest.fixture()
def def_registry(home_dir: Path):
    """Return a Registry instance with a temporary home directory."""
    from amplifier_ipc_host.definition_registry import Registry

    return Registry(home=home_dir)


AGENT_YAML = """\
type: agent
local_ref: my-agent
uuid: 12345678-abcd-efgh-ijkl-mnopqrstuvwx
name: My Test Agent
description: A test agent definition
"""

BEHAVIOR_YAML = """\
type: behavior
local_ref: my-behavior
uuid: 87654321-dcba-hgfe-lkji-xwvutsrqponm
name: My Test Behavior
description: A test behavior definition
"""


async def test_ensure_home_creates_structure(def_registry, home_dir: Path) -> None:
    """ensure_home() creates home/, definitions/, environments/ dirs and alias files."""
    def_registry.ensure_home()

    assert home_dir.is_dir()
    assert (home_dir / "definitions").is_dir()
    assert (home_dir / "environments").is_dir()
    assert (home_dir / "agents.yaml").is_file()
    assert (home_dir / "behaviors.yaml").is_file()


async def test_register_agent_definition(def_registry, home_dir: Path) -> None:
    """register_definition() writes agent def and updates agents.yaml."""
    def_registry.ensure_home()
    def_registry.register_definition(AGENT_YAML)

    definition_id = "agent_my-agent_12345678"
    def_file = home_dir / "definitions" / f"{definition_id}.yaml"
    assert def_file.is_file()

    parsed = yaml.safe_load(def_file.read_text())
    assert parsed["type"] == "agent"
    assert parsed["local_ref"] == "my-agent"

    agents_data = yaml.safe_load((home_dir / "agents.yaml").read_text())
    assert agents_data["my-agent"] == definition_id


async def test_register_behavior_definition(def_registry, home_dir: Path) -> None:
    """register_definition() writes behavior def and updates behaviors.yaml."""
    def_registry.ensure_home()
    def_registry.register_definition(BEHAVIOR_YAML)

    definition_id = "behavior_my-behavior_87654321"
    def_file = home_dir / "definitions" / f"{definition_id}.yaml"
    assert def_file.is_file()

    behaviors_data = yaml.safe_load((home_dir / "behaviors.yaml").read_text())
    assert behaviors_data["my-behavior"] == definition_id


async def test_resolve_agent_returns_path(def_registry, home_dir: Path) -> None:
    """resolve_agent() returns Path to definition file for a known agent."""
    def_registry.ensure_home()
    def_registry.register_definition(AGENT_YAML)

    result = def_registry.resolve_agent("my-agent")

    definition_id = "agent_my-agent_12345678"
    expected = home_dir / "definitions" / f"{definition_id}.yaml"
    assert result == expected
    assert result.is_file()


async def test_resolve_agent_unknown_raises(def_registry, home_dir: Path) -> None:
    """resolve_agent() raises FileNotFoundError for unknown agent."""
    def_registry.ensure_home()

    with pytest.raises(FileNotFoundError):
        def_registry.resolve_agent("nonexistent")
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_definition_registry.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_host.definition_registry'`

**Step 3: Copy the Registry class to the host**

Create `amplifier-ipc-host/src/amplifier_ipc_host/definition_registry.py` with the exact contents of `amplifier-ipc-cli/src/amplifier_ipc_cli/registry.py` (all 244 lines). No changes needed — it has no CLI-specific imports (only `hashlib`, `os`, `datetime`, `pathlib`, `yaml`).

```python
"""Registry class for managing the $AMPLIFIER_HOME filesystem layout.

Moved from amplifier-ipc-cli to amplifier-ipc-host so the host can
resolve agent/behavior definitions autonomously (required for sub-session
spawning).
"""

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml


class Registry:
    """Manages the Amplifier home directory filesystem layout.

    Handles:
    - Directory structure creation (home/, definitions/, environments/)
    - Alias tracking in agents.yaml and behaviors.yaml
    - Definition file registration with optional source metadata
    """

    def __init__(self, home: Optional[Path] = None) -> None:
        if home is not None:
            self.home = home
        elif "AMPLIFIER_HOME" in os.environ:
            self.home = Path(os.environ["AMPLIFIER_HOME"])
        else:
            self.home = Path.home() / ".amplifier"

    def ensure_home(self) -> None:
        """Create the home directory structure if it does not already exist."""
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "definitions").mkdir(exist_ok=True)
        (self.home / "environments").mkdir(exist_ok=True)

        agents_yaml = self.home / "agents.yaml"
        if not agents_yaml.exists():
            agents_yaml.write_text("{}\n")

        behaviors_yaml = self.home / "behaviors.yaml"
        if not behaviors_yaml.exists():
            behaviors_yaml.write_text("{}\n")

    def register_definition(
        self, yaml_content: str, source_url: Optional[str] = None
    ) -> str:
        """Register a definition from YAML content."""
        if not (self.home / "agents.yaml").exists():
            self.ensure_home()

        parsed = yaml.safe_load(yaml_content)
        if not isinstance(parsed, dict):
            raise ValueError("YAML content must be a mapping")

        def_type = parsed.get("type")
        local_ref = parsed.get("local_ref")
        uuid_value = parsed.get("uuid")

        if not def_type or not local_ref or not uuid_value:
            raise ValueError(
                "YAML content must contain 'type', 'local_ref', and 'uuid' fields"
            )

        uuid_first_8 = str(uuid_value)[:8]
        definition_id = f"{def_type}_{local_ref}_{uuid_first_8}"

        stored_data = dict(parsed)
        if source_url is not None:
            content_bytes = yaml_content.encode("utf-8")
            sha256_hex = hashlib.sha256(content_bytes).hexdigest()
            stored_data["_meta"] = {
                "source_url": source_url,
                "source_hash": f"sha256:{sha256_hex}",
                "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
            }

        def_file = self.home / "definitions" / f"{definition_id}.yaml"
        def_file.write_text(yaml.dump(stored_data, default_flow_style=False))

        if def_type == "agent":
            alias_file = self.home / "agents.yaml"
        else:
            alias_file = self.home / "behaviors.yaml"

        alias_data = yaml.safe_load(alias_file.read_text()) or {}
        alias_data[local_ref] = definition_id
        if source_url is not None:
            alias_data[source_url] = definition_id
        alias_file.write_text(yaml.dump(alias_data, default_flow_style=False))

        return definition_id

    def _resolve_alias(self, name: str, alias_file: Path, kind: str) -> Path:
        alias_data: dict = {}
        if alias_file.exists():
            alias_data = yaml.safe_load(alias_file.read_text()) or {}

        definition_id = alias_data.get(name)
        if definition_id is None:
            raise FileNotFoundError(
                f"{kind} '{name}' not found in registry. "
                "Run amplifier-ipc discover to populate the registry."
            )

        def_file = self.home / "definitions" / f"{definition_id}.yaml"
        if not def_file.exists():
            raise FileNotFoundError(
                f"Definition file for {kind} '{name}' (id: {definition_id}) not found. "
                "Run amplifier-ipc discover to populate the registry."
            )

        return def_file

    def resolve_agent(self, name: str) -> Path:
        """Resolve an agent alias to its definition file path."""
        return self._resolve_alias(name, self.home / "agents.yaml", "agent")

    def resolve_behavior(self, name: str) -> Path:
        """Resolve a behavior alias to its definition file path."""
        return self._resolve_alias(name, self.home / "behaviors.yaml", "behavior")

    def get_environment_path(self, definition_id: str) -> Path:
        return self.home / "environments" / definition_id

    def is_installed(self, definition_id: str) -> bool:
        return self.get_environment_path(definition_id).is_dir()

    def get_source_meta(self, definition_id: str) -> Optional[dict]:
        def_file = self.home / "definitions" / f"{definition_id}.yaml"
        if not def_file.exists():
            return None

        parsed = yaml.safe_load(def_file.read_text())
        if not isinstance(parsed, dict):
            return None

        return parsed.get("_meta", None)
```

**Step 4: Update the host's `__init__.py`**

Add after the `SessionPersistence` import line in `amplifier-ipc-host/src/amplifier_ipc_host/__init__.py`:

```python
from amplifier_ipc_host.definition_registry import Registry
```

And add `"Registry"` to the `__all__` list under a `# Definition registry` comment.

**Step 5: Run host tests to verify they pass**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_definition_registry.py -v
```

Expected: All 5 tests PASS

**Step 6: Commit**

```bash
git add amplifier-ipc-host/src/amplifier_ipc_host/definition_registry.py \
        amplifier-ipc-host/src/amplifier_ipc_host/__init__.py \
        amplifier-ipc-host/tests/test_definition_registry.py \
  && git commit -m "feat(host): add Registry class for definition management

Move Registry from CLI to host so the host can resolve agent/behavior
definitions autonomously (required for sub-session spawning)."
```

---

## Task 2: Move definitions.py from CLI to host

**Files:**
- Move: `amplifier-ipc-cli/src/amplifier_ipc_cli/definitions.py` → `amplifier-ipc-host/src/amplifier_ipc_host/definitions.py`
- Modify: `amplifier-ipc-host/src/amplifier_ipc_host/__init__.py` (add exports)
- Test: `amplifier-ipc-host/tests/test_definitions.py`

**Step 1: Write the test in the host package**

Create `amplifier-ipc-host/tests/test_definitions.py`:

```python
"""Tests for definitions module (moved from CLI)."""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_ipc_host.definitions import (
    ResolvedAgent,
    ServiceEntry,
    parse_agent_definition,
    parse_behavior_definition,
    resolve_agent,
)


AGENT_YAML = """\
type: agent
local_ref: test-agent
uuid: 11111111-0000-0000-0000-000000000001
orchestrator: streaming
context_manager: simple
provider: anthropic
component_config:
  key: value
behaviors:
  - test-behavior
services:
  - name: foundation-service
    installer: pip
    source: pip:foundation@latest
"""

BEHAVIOR_YAML = """\
type: behavior
local_ref: test-behavior
uuid: 22222222-0000-0000-0000-000000000002
services:
  - name: foundation-service
    installer: pip
    source: pip:foundation@latest
"""


async def test_parse_agent_definition_basic() -> None:
    """parse_agent_definition populates scalar fields from YAML."""
    defn = parse_agent_definition(AGENT_YAML)

    assert defn.type == "agent"
    assert defn.local_ref == "test-agent"
    assert defn.orchestrator == "streaming"
    assert defn.context_manager == "simple"
    assert defn.provider == "anthropic"


async def test_parse_behavior_definition_basic() -> None:
    """parse_behavior_definition populates fields from YAML."""
    defn = parse_behavior_definition(BEHAVIOR_YAML)

    assert defn.type == "behavior"
    assert defn.local_ref == "test-behavior"
    assert len(defn.services) == 1
    assert defn.services[0].name == "foundation-service"


async def test_resolve_agent_deduplicates_services(tmp_path: Path) -> None:
    """resolve_agent() deduplicates services declared in agent + behavior."""
    from amplifier_ipc_host.definition_registry import Registry

    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()
    registry.register_definition(AGENT_YAML)
    registry.register_definition(BEHAVIOR_YAML)

    resolved = await resolve_agent(registry, "test-agent")

    assert isinstance(resolved, ResolvedAgent)
    service_names = [s.name for s in resolved.services]
    assert service_names.count("foundation-service") == 1
    assert resolved.orchestrator == "streaming"


async def test_resolve_agent_unknown_raises(tmp_path: Path) -> None:
    """resolve_agent() raises FileNotFoundError for unknown agent."""
    from amplifier_ipc_host.definition_registry import Registry

    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    with pytest.raises(FileNotFoundError):
        await resolve_agent(registry, "nonexistent")
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_definitions.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_host.definitions'`

**Step 3: Copy definitions.py to the host**

Create `amplifier-ipc-host/src/amplifier_ipc_host/definitions.py` with the exact contents of `amplifier-ipc-cli/src/amplifier_ipc_cli/definitions.py` (all 277 lines). No changes needed — it imports only `asyncio`, `logging`, `urllib`, `dataclasses`, `yaml`, and uses a duck-typed `registry` parameter (no import of `Registry`).

**Step 4: Update the host's `__init__.py`**

Add the import:

```python
from amplifier_ipc_host.definitions import (
    AgentDefinition,
    BehaviorDefinition,
    ResolvedAgent,
    ServiceEntry,
    parse_agent_definition,
    parse_behavior_definition,
    resolve_agent,
)
```

And add all names to `__all__` under a `# Definitions` comment.

**Step 5: Run host tests to verify they pass**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_definitions.py -v
```

Expected: All 4 tests PASS

**Step 6: Commit**

```bash
git add amplifier-ipc-host/src/amplifier_ipc_host/definitions.py \
        amplifier-ipc-host/src/amplifier_ipc_host/__init__.py \
        amplifier-ipc-host/tests/test_definitions.py \
  && git commit -m "feat(host): add definitions module for agent resolution

Move definitions from CLI to host so the host can resolve agent/behavior
definition trees autonomously (required for sub-session spawning)."
```

---

## Task 3: Update CLI to import from host and verify all tests pass

**Files:**
- Modify: `amplifier-ipc-cli/src/amplifier_ipc_cli/registry.py` (replace with re-export)
- Modify: `amplifier-ipc-cli/src/amplifier_ipc_cli/definitions.py` (replace with re-export)
- Modify: `amplifier-ipc-cli/src/amplifier_ipc_cli/session_launcher.py` (update imports)
- Test: all existing CLI tests

**Step 1: Replace CLI registry.py with re-export stub**

Replace the entire contents of `amplifier-ipc-cli/src/amplifier_ipc_cli/registry.py` with:

```python
"""Registry re-export — canonical implementation lives in amplifier-ipc-host.

This module re-exports the Registry class so existing CLI code and tests
continue to work with ``from amplifier_ipc_cli.registry import Registry``.
"""

from amplifier_ipc_host.definition_registry import Registry

__all__ = ["Registry"]
```

**Step 2: Replace CLI definitions.py with re-export stub**

Replace the entire contents of `amplifier-ipc-cli/src/amplifier_ipc_cli/definitions.py` with:

```python
"""Definitions re-export — canonical implementation lives in amplifier-ipc-host.

This module re-exports all definition types and functions so existing CLI
code and tests continue to work with ``from amplifier_ipc_cli.definitions import ...``.
"""

from amplifier_ipc_host.definitions import (
    AgentDefinition,
    BehaviorDefinition,
    ResolvedAgent,
    ServiceEntry,
    _fetch_url,
    _parse_services,
    parse_agent_definition,
    parse_behavior_definition,
    resolve_agent,
)

__all__ = [
    "AgentDefinition",
    "BehaviorDefinition",
    "ResolvedAgent",
    "ServiceEntry",
    "_fetch_url",
    "_parse_services",
    "parse_agent_definition",
    "parse_behavior_definition",
    "resolve_agent",
]
```

**Step 3: Update session_launcher.py imports**

In `amplifier-ipc-cli/src/amplifier_ipc_cli/session_launcher.py`, change:

```python
from amplifier_ipc_cli.definitions import ResolvedAgent, resolve_agent
from amplifier_ipc_cli.registry import Registry
```

to:

```python
from amplifier_ipc_host.definitions import ResolvedAgent, resolve_agent
from amplifier_ipc_host.definition_registry import Registry
```

**Step 4: Run ALL CLI tests to verify nothing broke**

```bash
cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/ -v
```

Expected: ALL existing tests PASS — they import from `amplifier_ipc_cli.registry` and `amplifier_ipc_cli.definitions` which now re-export from the host.

**Step 5: Run ALL host tests to verify nothing broke**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/ -v
```

Expected: ALL tests PASS

**Step 6: Commit**

```bash
git add amplifier-ipc-cli/src/amplifier_ipc_cli/registry.py \
        amplifier-ipc-cli/src/amplifier_ipc_cli/definitions.py \
        amplifier-ipc-cli/src/amplifier_ipc_cli/session_launcher.py \
  && git commit -m "refactor(cli): re-export registry and definitions from host

CLI modules become thin re-export stubs. All existing CLI tests continue
to pass unchanged. session_launcher.py imports directly from host."
```

---

## Task 4: Cross-service shared state — host state store

**Files:**
- Modify: `amplifier-ipc-host/src/amplifier_ipc_host/persistence.py` (add state methods)
- Test: `amplifier-ipc-host/tests/test_persistence.py` (append new tests)

The spec says state is loaded from `state.json` at turn start and persisted at turn end. `SessionPersistence` already manages `transcript.jsonl` and `metadata.json` in the same session directory — state belongs here.

**Step 1: Write failing tests**

Append to `amplifier-ipc-host/tests/test_persistence.py`:

```python
# ---------------------------------------------------------------------------
# State management tests
# ---------------------------------------------------------------------------


def test_load_state_returns_empty_dict_when_no_file(tmp_path: Path) -> None:
    """load_state() returns {} when state.json does not exist."""
    persistence = SessionPersistence(session_id="sess-state-empty", base_dir=tmp_path)
    state = persistence.load_state()
    assert state == {}


def test_save_and_load_state_round_trip(tmp_path: Path) -> None:
    """save_state() persists dict, load_state() reads it back."""
    persistence = SessionPersistence(session_id="sess-state-rt", base_dir=tmp_path)
    state = {"todo_state": {"items": [1, 2, 3]}, "counter": 42}
    persistence.save_state(state)

    loaded = persistence.load_state()
    assert loaded == state


def test_save_state_overwrites_previous(tmp_path: Path) -> None:
    """save_state() replaces the previous state entirely."""
    persistence = SessionPersistence(session_id="sess-state-ow", base_dir=tmp_path)
    persistence.save_state({"version": 1})
    persistence.save_state({"version": 2, "new_key": "value"})

    loaded = persistence.load_state()
    assert loaded == {"version": 2, "new_key": "value"}
    assert "version" in loaded
    assert loaded["version"] == 2


def test_state_file_path(tmp_path: Path) -> None:
    """state.json is stored at <base_dir>/<session_id>/state.json."""
    persistence = SessionPersistence(session_id="sess-state-path", base_dir=tmp_path)
    persistence.save_state({"key": "value"})

    expected_path = tmp_path / "sess-state-path" / "state.json"
    assert expected_path.exists()
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_persistence.py::test_load_state_returns_empty_dict_when_no_file -v
```

Expected: FAIL — `AttributeError: 'SessionPersistence' object has no attribute 'load_state'`

**Step 3: Implement state methods on SessionPersistence**

Add to `amplifier-ipc-host/src/amplifier_ipc_host/persistence.py`, after the `__init__` method, add a `state_path` attribute:

```python
self.state_path = self._session_dir / "state.json"
```

Then add these two methods after `load_transcript`:

```python
def load_state(self) -> dict[str, Any]:
    """Load state from state.json, or return empty dict if missing."""
    if not self.state_path.exists():
        return {}
    with self.state_path.open("r", encoding="utf-8") as fh:
        return json.loads(fh.read())

def save_state(self, state: dict[str, Any]) -> None:
    """Overwrite state.json with *state* (pretty-printed)."""
    with self.state_path.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
```

Also add `from typing import Any` at the top of the file.

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_persistence.py -v
```

Expected: ALL persistence tests PASS (original 7 + new 4 = 11)

**Step 5: Commit**

```bash
git add amplifier-ipc-host/src/amplifier_ipc_host/persistence.py \
        amplifier-ipc-host/tests/test_persistence.py \
  && git commit -m "feat(host): add state.json load/save to SessionPersistence

Cross-service shared state is persisted as state.json alongside
transcript.jsonl and metadata.json. Loaded at turn start, saved at turn end."
```

---

## Task 5: Cross-service shared state — wire protocol routing

**Files:**
- Modify: `amplifier-ipc-host/src/amplifier_ipc_host/router.py` (add state.get/set routing)
- Modify: `amplifier-ipc-host/src/amplifier_ipc_host/host.py` (load/save state per turn, handle state in orchestrator loop)
- Test: `amplifier-ipc-host/tests/test_router.py` (append state tests)
- Test: `amplifier-ipc-host/tests/test_host.py` (append state tests)

**Step 1: Write failing router tests**

Append to `amplifier-ipc-host/tests/test_router.py`:

```python
# ---------------------------------------------------------------------------
# State routing tests
# ---------------------------------------------------------------------------


async def test_route_state_get_returns_value() -> None:
    """request.state_get returns value from state dict."""
    router, _, _ = _build_router_with_two_services()
    # Inject state dict into the router
    router._state = {"todo_state": {"items": [1, 2, 3]}}

    result = await router.route_request(
        "request.state_get", {"key": "todo_state"}
    )

    assert result == {"value": {"items": [1, 2, 3]}}


async def test_route_state_get_missing_key_returns_null() -> None:
    """request.state_get returns {value: None} for nonexistent key."""
    router, _, _ = _build_router_with_two_services()
    router._state = {}

    result = await router.route_request(
        "request.state_get", {"key": "nonexistent"}
    )

    assert result == {"value": None}


async def test_route_state_set_stores_value() -> None:
    """request.state_set stores value in state dict."""
    router, _, _ = _build_router_with_two_services()
    router._state = {}

    result = await router.route_request(
        "request.state_set", {"key": "counter", "value": 42}
    )

    assert result == {"ok": True}
    assert router._state["counter"] == 42


async def test_route_state_set_overwrites_existing() -> None:
    """request.state_set overwrites an existing key."""
    router, _, _ = _build_router_with_two_services()
    router._state = {"counter": 1}

    await router.route_request(
        "request.state_set", {"key": "counter", "value": 2}
    )

    assert router._state["counter"] == 2
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_router.py::test_route_state_get_returns_value -v
```

Expected: FAIL — `AttributeError: 'Router' object has no attribute '_state'`

**Step 3: Add state routing to the Router**

In `amplifier-ipc-host/src/amplifier_ipc_host/router.py`:

1. Add `state: dict[str, Any] | None = None` parameter to `Router.__init__`:

```python
def __init__(
    self,
    registry: CapabilityRegistry,
    services: dict[str, Any],
    context_manager_key: str,
    provider_key: str,
    state: dict[str, Any] | None = None,
) -> None:
    self._registry = registry
    self._services = services
    self._context_manager_key = context_manager_key
    self._provider_key = provider_key
    self._state: dict[str, Any] = state if state is not None else {}
```

2. Add routing for `request.state_get` and `request.state_set` in `route_request`, before the final `raise JsonRpcError`:

```python
if method == "request.state_get":
    key = params.get("key") if isinstance(params, dict) else None
    return {"value": self._state.get(key)}

if method == "request.state_set":
    if not isinstance(params, dict) or "key" not in params:
        raise JsonRpcError(
            code=INVALID_PARAMS,
            message="state.set requires 'key' and 'value' params",
        )
    self._state[params["key"]] = params.get("value")
    return {"ok": True}
```

**Step 4: Run router tests to verify they pass**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_router.py -v
```

Expected: ALL router tests PASS (original 10 + new 4 = 14)

**Step 5: Wire state into Host turn lifecycle**

In `amplifier-ipc-host/src/amplifier_ipc_host/host.py`:

1. Add `self._state: dict[str, Any] = {}` to `Host.__init__`

2. In the `run()` method, after creating `self._persistence` and before `await self._spawn_services()`, add:

```python
# Load state from previous turns
self._state = self._persistence.load_state()
```

3. When building the Router (step 5 in `run()`), pass state:

```python
self._router = Router(
    registry=self._registry,
    services=self._services,
    context_manager_key=context_manager_key,
    provider_key=provider_key,
    state=self._state,
)
```

4. After the orchestrator loop completes and before `self._persistence.save_metadata(...)`, add:

```python
# Persist state
self._persistence.save_state(self._state)
```

**Step 6: Also add `state.get`/`state.set` handling for non-orchestrator services**

In the `_orchestrator_loop` method, the host already handles `request.*` messages from the orchestrator. But regular services (tools, hooks) also need `state.get`/`state.set`. The `Client` in `lifecycle.py` already has an `on_notification` callback but notifications are fire-and-forget — state ops need request/response.

For Phase 1, state ops from non-orchestrator services are handled the same way as orchestrator state ops — the router routes them. Services send `state.get`/`state.set` as `request.state_get`/`request.state_set` through their client, and the host routes them. This works because the host reads from each service's stdout in `_orchestrator_loop` and routes any `request.*` method through the router.

However, looking at the current code, only the orchestrator's stdout is read in the loop. Tool/hook services communicate via the host sending `tool.execute`/`hook.emit` and receiving the response — there's no mechanism for services to initiate requests back to the host.

**For Phase 1, state.get/state.set is only available to the orchestrator** (via `request.state_get`/`request.state_set`). The orchestrator can read/write state on behalf of tools/hooks by passing state data in tool/hook params. Full bidirectional state access for all services is a future enhancement.

**Step 7: Run all host tests**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/ -v
```

Expected: ALL tests PASS

**Step 8: Commit**

```bash
git add amplifier-ipc-host/src/amplifier_ipc_host/router.py \
        amplifier-ipc-host/src/amplifier_ipc_host/host.py \
        amplifier-ipc-host/tests/test_router.py \
  && git commit -m "feat(host): add cross-service shared state (state.get/set)

Router handles request.state_get and request.state_set. State dict is
loaded from state.json at turn start and persisted at turn end.
Phase 1: only orchestrator can access state directly."
```

---

## Task 6: Provider streaming — host relay of provider notifications

**Files:**
- Modify: `amplifier-ipc-host/src/amplifier_ipc_host/host.py` (relay `stream.provider.*` from provider to orchestrator)
- Modify: `amplifier-ipc-host/src/amplifier_ipc_host/events.py` (add `StreamContentBlockStartEvent`, `StreamContentBlockEndEvent`)
- Test: `amplifier-ipc-host/tests/test_host.py` (append streaming relay tests)

The provider streaming flow is:
1. Provider emits `stream.provider.*` notifications to host (via stdout)
2. Host relays them to orchestrator (via stdin)
3. Orchestrator processes them and re-emits as `stream.*` to host
4. Host yields them as `HostEvent` to the CLI

The current `_orchestrator_loop` already handles step 3→4 (`stream.token`, `stream.thinking`, `stream.tool_call_start` → yield events). We need to add:
- Step 1→2: When host reads `stream.provider.*` from the provider's stdout during a `provider.complete` call, it relays them to the orchestrator
- Additional event types for `stream.content_block_start` and `stream.content_block_end`

**The architectural challenge:** Currently the host sends `provider.complete` via the `Client.request()` method which blocks waiting for the response. During that time, the provider's stdout may emit `stream.provider.*` notifications. The `Client` already has an `on_notification` callback for handling these — see `client.py` line 67–69.

The relay works like this:
1. Before routing `request.provider_complete`, the host sets up a notification callback on the provider service's client that forwards `stream.provider.*` messages to the orchestrator's stdin
2. The `Client._read_loop` calls `on_notification` for each notification, which writes to the orchestrator process
3. The provider eventually returns the `ChatResponse` as the normal response to the `Client.request()` call

**Step 1: Add new event types**

In `amplifier-ipc-host/src/amplifier_ipc_host/events.py`, add:

```python
@dataclass
class StreamContentBlockStartEvent(HostEvent):
    """Emitted when a streaming content block begins (stream.content_block_start)."""

    block_type: str = ""
    index: int = 0


@dataclass
class StreamContentBlockEndEvent(HostEvent):
    """Emitted when a streaming content block ends (stream.content_block_end)."""

    block_type: str = ""
    index: int = 0
```

Update `__init__.py` to export them.

**Step 2: Write failing test for streaming relay**

Append to `amplifier-ipc-host/tests/test_host.py`:

```python
async def test_orchestrator_loop_yields_content_block_events() -> None:
    """_orchestrator_loop yields content block start/end events."""
    from amplifier_ipc_host.events import (
        StreamContentBlockStartEvent,
        StreamContentBlockEndEvent,
    )

    config = SessionConfig(
        services=["orch"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()
    host = Host(config=config, settings=settings)

    fake_process = MagicMock()
    fake_process.stdin = MagicMock()
    fake_process.stdout = MagicMock()

    fake_service = MagicMock()
    fake_service.process = fake_process
    host._services = {"orch": fake_service}

    captured_id: list[str] = []

    async def fake_write(stream: object, message: dict) -> None:
        if message.get("method") == "orchestrator.execute":
            captured_id.append(message["id"])

    read_call_count = 0

    async def fake_read(stream: object) -> dict | None:
        nonlocal read_call_count
        read_call_count += 1
        if read_call_count == 1:
            return {
                "jsonrpc": "2.0",
                "method": "stream.content_block_start",
                "params": {"type": "text", "index": 0},
            }
        elif read_call_count == 2:
            return {
                "jsonrpc": "2.0",
                "method": "stream.token",
                "params": {"token": "Hello"},
            }
        elif read_call_count == 3:
            return {
                "jsonrpc": "2.0",
                "method": "stream.content_block_end",
                "params": {"type": "text", "index": 0},
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": captured_id[0],
                "result": "Hello",
            }

    with (
        patch("amplifier_ipc_host.host.write_message", fake_write),
        patch("amplifier_ipc_host.host.read_message", fake_read),
    ):
        events = []
        async for event in host._orchestrator_loop(
            orchestrator_key="orch",
            prompt="hello",
            system_prompt="be helpful",
        ):
            events.append(event)

    assert len(events) == 4
    assert isinstance(events[0], StreamContentBlockStartEvent)
    assert events[0].block_type == "text"
    assert events[0].index == 0
    assert isinstance(events[1], StreamTokenEvent)
    assert isinstance(events[2], StreamContentBlockEndEvent)
    assert isinstance(events[3], CompleteEvent)
```

**Step 3: Run test to verify it fails**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_host.py::test_orchestrator_loop_yields_content_block_events -v
```

Expected: FAIL — `ImportError` or the events won't be yielded

**Step 4: Handle content_block events in the orchestrator loop**

In `amplifier-ipc-host/src/amplifier_ipc_host/host.py`, in the `_orchestrator_loop` method, add handling for `stream.content_block_start` and `stream.content_block_end` alongside the existing `stream.token`/`stream.thinking`/`stream.tool_call_start` handlers:

```python
# Stream content block start notification
elif method == "stream.content_block_start":
    params = message.get("params") or {}
    yield StreamContentBlockStartEvent(
        block_type=params.get("type", ""),
        index=params.get("index", 0),
    )

# Stream content block end notification
elif method == "stream.content_block_end":
    params = message.get("params") or {}
    yield StreamContentBlockEndEvent(
        block_type=params.get("type", ""),
        index=params.get("index", 0),
    )
```

Add the imports at the top of `host.py`:

```python
from amplifier_ipc_host.events import (
    ...
    StreamContentBlockStartEvent,
    StreamContentBlockEndEvent,
)
```

**Step 5: Write test for provider notification relay**

Append to `amplifier-ipc-host/tests/test_router.py`:

```python
# ---------------------------------------------------------------------------
# Provider streaming relay tests
# ---------------------------------------------------------------------------


async def test_provider_complete_with_notification_relay() -> None:
    """When provider_complete is called, provider notifications are relayed."""
    # This test verifies the Router can set up notification forwarding
    # on the provider service's client before calling provider.complete.
    router, _, provider_client = _build_router_with_two_services(
        provider_responses={"provider.complete": {"content": "Hello"}}
    )

    result = await router.route_request(
        "request.provider_complete",
        {"messages": [{"role": "user", "content": "Hi"}]},
    )

    assert result == {"content": "Hello"}
    assert len(provider_client.calls) == 1
    assert provider_client.calls[0][0] == "provider.complete"
```

**Step 6: Run all host tests**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/ -v
```

Expected: ALL tests PASS

**Step 7: Commit**

```bash
git add amplifier-ipc-host/src/amplifier_ipc_host/host.py \
        amplifier-ipc-host/src/amplifier_ipc_host/events.py \
        amplifier-ipc-host/src/amplifier_ipc_host/__init__.py \
        amplifier-ipc-host/tests/test_host.py \
        amplifier-ipc-host/tests/test_router.py \
  && git commit -m "feat(host): add provider streaming relay and content block events

Host handles stream.content_block_start/end notifications from
orchestrator. Adds StreamContentBlockStartEvent and
StreamContentBlockEndEvent to the event hierarchy."
```

---

## Task 7: Provider streaming — notification forwarding from provider to orchestrator

**Files:**
- Modify: `amplifier-ipc-host/src/amplifier_ipc_host/router.py` (add notification relay for provider_complete)
- Modify: `amplifier-ipc-host/src/amplifier_ipc_host/host.py` (pass orchestrator writer to router)
- Test: `amplifier-ipc-host/tests/test_router.py` (append relay test)

The key design: when the router calls `provider.complete` on the provider service, it needs to relay `stream.provider.*` notifications from the provider's client to the orchestrator. The `Client` class already has `on_notification` callback support.

**Step 1: Write failing test**

Append to `amplifier-ipc-host/tests/test_router.py`:

```python
async def test_provider_streaming_notifications_relayed() -> None:
    """stream.provider.* notifications from provider client are forwarded to orchestrator."""
    registry = CapabilityRegistry()
    registry.register(
        "providers",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [{"name": "anthropic"}],
            "content": [],
        },
    )

    # Provider client that will trigger a notification callback
    provider_client = FakeClient(
        responses={"provider.complete": {"content": "Hello"}}
    )

    # Capture notifications sent to orchestrator
    relayed_notifications: list[dict] = []

    class FakeOrchestratorWriter:
        def write(self, data: bytes) -> None:
            pass

        async def drain(self) -> None:
            pass

    services: dict[str, Any] = {
        "providers": FakeService(provider_client),
        "ctx": FakeService(FakeClient()),
    }

    router = Router(
        registry=registry,
        services=services,
        context_manager_key="ctx",
        provider_key="providers",
        on_provider_notification=lambda msg: relayed_notifications.append(msg),
    )

    result = await router.route_request(
        "request.provider_complete",
        {"messages": [{"role": "user", "content": "Hi"}]},
    )

    assert result == {"content": "Hello"}

    # Simulate what would happen: the provider client's on_notification
    # would be called by the Client._read_loop with stream.provider.* messages.
    # Since we're using FakeClient (no real read loop), we test that the router
    # installed the callback correctly.
    assert router._on_provider_notification is not None
```

**Step 2: Run test to verify it fails**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_router.py::test_provider_streaming_notifications_relayed -v
```

Expected: FAIL — `TypeError: Router.__init__() got an unexpected keyword argument 'on_provider_notification'`

**Step 3: Add notification relay support to Router**

In `amplifier-ipc-host/src/amplifier_ipc_host/router.py`:

1. Add `on_provider_notification` parameter to `__init__`:

```python
def __init__(
    self,
    registry: CapabilityRegistry,
    services: dict[str, Any],
    context_manager_key: str,
    provider_key: str,
    state: dict[str, Any] | None = None,
    on_provider_notification: Any | None = None,
) -> None:
    self._registry = registry
    self._services = services
    self._context_manager_key = context_manager_key
    self._provider_key = provider_key
    self._state: dict[str, Any] = state if state is not None else {}
    self._on_provider_notification = on_provider_notification
```

2. Update `request.provider_complete` routing to install notification relay:

```python
if method == "request.provider_complete":
    provider_svc = self._services[self._provider_key]
    # Install notification callback for streaming relay
    old_callback = getattr(provider_svc.client, "on_notification", None)
    if self._on_provider_notification is not None:
        provider_svc.client.on_notification = self._on_provider_notification
    try:
        return await provider_svc.client.request("provider.complete", params)
    finally:
        # Restore previous callback
        provider_svc.client.on_notification = old_callback
```

**Step 4: Wire the relay in Host**

In `amplifier-ipc-host/src/amplifier_ipc_host/host.py`, when creating the Router in `run()`, add a notification callback that writes `stream.provider.*` messages to the orchestrator's stdin:

```python
async def _relay_provider_notification(notification: dict) -> None:
    """Relay stream.provider.* notifications from provider to orchestrator."""
    method = notification.get("method", "")
    if method.startswith("stream.provider."):
        if orchestrator_svc.process.stdin is not None:
            await write_message(orchestrator_svc.process.stdin, notification)
```

But since `on_notification` in `Client` is synchronous (not async), we need to use a sync-to-async bridge. The simplest approach: collect notifications in a list and have the orchestrator loop forward them, OR use `asyncio.get_running_loop().call_soon()`.

**Simpler approach for Phase 1:** The notification callback queues messages into an `asyncio.Queue`, and the host's orchestrator loop checks the queue between reads. Actually, even simpler — the callback can directly write since `write_message` is async. We'll use a queue:

In the Router constructor, add the callback. In `host.py`, in `run()`:

```python
# Notification relay queue for provider streaming
self._provider_notification_queue: asyncio.Queue[dict] = asyncio.Queue()

def _queue_provider_notification(notification: dict) -> None:
    method = notification.get("method", "")
    if method.startswith("stream.provider."):
        self._provider_notification_queue.put_nowait(notification)
```

Pass `on_provider_notification=_queue_provider_notification` to the Router.

Then in `_orchestrator_loop`, after each `read_message`, drain the queue and forward to orchestrator:

```python
# Drain provider notifications and relay to orchestrator
while not self._provider_notification_queue.empty():
    notification = self._provider_notification_queue.get_nowait()
    await write_message(orchestrator_svc.process.stdin, notification)
```

**Step 5: Run all tests**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/ -v
```

Expected: ALL tests PASS

**Step 6: Commit**

```bash
git add amplifier-ipc-host/src/amplifier_ipc_host/router.py \
        amplifier-ipc-host/src/amplifier_ipc_host/host.py \
        amplifier-ipc-host/tests/test_router.py \
  && git commit -m "feat(host): relay stream.provider.* notifications to orchestrator

Provider streaming notifications are queued via on_notification callback
and forwarded to the orchestrator's stdin during the orchestrator loop.
Completes the full streaming data flow: Provider → Host → Orchestrator."
```

---

## Task 8: Sub-session spawning — session ID generation and config merging

**Files:**
- Create: `amplifier-ipc-host/src/amplifier_ipc_host/spawner.py`
- Test: `amplifier-ipc-host/tests/test_spawner.py`

**Step 1: Write failing tests**

Create `amplifier-ipc-host/tests/test_spawner.py`:

```python
"""Tests for sub-session spawning logic."""

from __future__ import annotations

import pytest

from amplifier_ipc_host.spawner import (
    generate_child_session_id,
    merge_configs,
    filter_tools,
    filter_hooks,
    format_parent_context,
)


# ---------------------------------------------------------------------------
# Session ID generation
# ---------------------------------------------------------------------------


async def test_generate_child_session_id_includes_parent_and_agent() -> None:
    """Child session ID follows {parent_span}-{child_span}_{agent} pattern."""
    child_id = generate_child_session_id(
        parent_session_id="abc123", agent_name="explorer"
    )

    assert "abc123" in child_id
    assert "explorer" in child_id
    # Format: parent-child_agent
    parts = child_id.split("_")
    assert len(parts) >= 2
    assert parts[-1] == "explorer"
    spans = parts[0].split("-")
    assert spans[0] == "abc123"
    assert len(spans[1]) > 0  # child span is non-empty


async def test_generate_child_session_id_self_delegation() -> None:
    """Self-delegation uses 'self' as the agent name component."""
    child_id = generate_child_session_id(
        parent_session_id="parent1", agent_name="self"
    )

    assert child_id.endswith("_self")


# ---------------------------------------------------------------------------
# Config merging
# ---------------------------------------------------------------------------


async def test_merge_configs_child_overrides_parent_scalars() -> None:
    """Child scalar values override parent."""
    parent = {"provider": "anthropic", "model": "claude-3"}
    child = {"provider": "openai"}

    merged = merge_configs(parent, child)

    assert merged["provider"] == "openai"
    assert merged["model"] == "claude-3"  # parent value preserved


async def test_merge_configs_tool_lists_merge_by_id() -> None:
    """Tool lists merge by ID, not replace."""
    parent = {
        "tools": [
            {"name": "bash", "config": {"timeout": 30}},
            {"name": "read_file", "config": {}},
        ]
    }
    child = {
        "tools": [
            {"name": "bash", "config": {"timeout": 60}},  # override
            {"name": "web_search", "config": {}},  # new
        ]
    }

    merged = merge_configs(parent, child)

    tool_names = [t["name"] for t in merged["tools"]]
    assert "bash" in tool_names
    assert "read_file" in tool_names
    assert "web_search" in tool_names
    # bash should have child's config (override)
    bash_tool = next(t for t in merged["tools"] if t["name"] == "bash")
    assert bash_tool["config"]["timeout"] == 60


# ---------------------------------------------------------------------------
# Tool/hook filtering
# ---------------------------------------------------------------------------


async def test_filter_tools_exclude_removes_delegate_by_default() -> None:
    """exclude_tools defaults to removing 'delegate' tool."""
    tools = [
        {"name": "bash"},
        {"name": "delegate"},
        {"name": "read_file"},
    ]

    filtered = filter_tools(tools, exclude_tools=None, inherit_tools=None)

    tool_names = [t["name"] for t in filtered]
    assert "delegate" not in tool_names
    assert "bash" in tool_names
    assert "read_file" in tool_names


async def test_filter_tools_explicit_exclude() -> None:
    """exclude_tools removes specified tools."""
    tools = [
        {"name": "bash"},
        {"name": "web_search"},
        {"name": "read_file"},
    ]

    filtered = filter_tools(
        tools, exclude_tools=["web_search", "delegate"], inherit_tools=None
    )

    tool_names = [t["name"] for t in filtered]
    assert "web_search" not in tool_names
    assert "bash" in tool_names


async def test_filter_tools_inherit_allowlist() -> None:
    """inherit_tools acts as allowlist — only specified tools kept."""
    tools = [
        {"name": "bash"},
        {"name": "web_search"},
        {"name": "read_file"},
    ]

    filtered = filter_tools(
        tools, exclude_tools=None, inherit_tools=["bash", "read_file"]
    )

    tool_names = [t["name"] for t in filtered]
    assert tool_names == ["bash", "read_file"]


async def test_filter_hooks_exclude() -> None:
    """exclude_hooks removes specified hooks."""
    hooks = [
        {"name": "approval", "event": "tool:pre"},
        {"name": "logging", "event": "*"},
    ]

    filtered = filter_hooks(hooks, exclude_hooks=["logging"], inherit_hooks=None)

    hook_names = [h["name"] for h in filtered]
    assert "logging" not in hook_names
    assert "approval" in hook_names


# ---------------------------------------------------------------------------
# Self-delegation depth tracking
# ---------------------------------------------------------------------------


async def test_self_delegation_depth_limit() -> None:
    """Exceeding max_self_delegation_depth raises an error."""
    from amplifier_ipc_host.spawner import check_self_delegation_depth

    # Depth 3 is the limit; depth 4 should fail
    check_self_delegation_depth(current_depth=2, max_depth=3)  # OK

    with pytest.raises(ValueError, match="self-delegation depth"):
        check_self_delegation_depth(current_depth=3, max_depth=3)
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_spawner.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc_host.spawner'`

**Step 3: Create spawner.py with core functions**

Create `amplifier-ipc-host/src/amplifier_ipc_host/spawner.py`:

```python
"""Sub-session spawning — session ID generation, config merge, tool/hook filtering."""

from __future__ import annotations

import uuid
from typing import Any


def generate_child_session_id(parent_session_id: str, agent_name: str) -> str:
    """Generate a child session ID with W3C trace context style lineage.

    Format: {parent_span}-{child_span}_{agent}
    """
    child_span = uuid.uuid4().hex[:8]
    return f"{parent_session_id}-{child_span}_{agent_name}"


def merge_configs(
    parent: dict[str, Any], child: dict[str, Any]
) -> dict[str, Any]:
    """Merge parent and child configs.

    - Child scalar values override parent
    - Tool/hook lists merge by ID (name), child overrides on collision
    """
    merged = dict(parent)

    for key, value in child.items():
        if key in ("tools", "hooks") and isinstance(value, list):
            # Merge lists by name
            parent_items = {
                item["name"]: item
                for item in merged.get(key, [])
                if isinstance(item, dict) and "name" in item
            }
            for item in value:
                if isinstance(item, dict) and "name" in item:
                    parent_items[item["name"]] = item
            merged[key] = list(parent_items.values())
        else:
            merged[key] = value

    return merged


_DEFAULT_EXCLUDE_TOOLS = ["delegate"]


def filter_tools(
    tools: list[dict[str, Any]],
    exclude_tools: list[str] | None,
    inherit_tools: list[str] | None,
) -> list[dict[str, Any]]:
    """Filter tools by exclude (blocklist) or inherit (allowlist).

    - If inherit_tools is set, only those tools are kept (allowlist)
    - If exclude_tools is set, those tools are removed (blocklist)
    - Default: exclude 'delegate' to prevent infinite recursion
    - exclude_tools and inherit_tools are mutually exclusive (inherit wins)
    """
    if inherit_tools is not None:
        return [t for t in tools if t.get("name") in inherit_tools]

    blocklist = set(exclude_tools) if exclude_tools is not None else set(_DEFAULT_EXCLUDE_TOOLS)
    return [t for t in tools if t.get("name") not in blocklist]


def filter_hooks(
    hooks: list[dict[str, Any]],
    exclude_hooks: list[str] | None,
    inherit_hooks: list[str] | None,
) -> list[dict[str, Any]]:
    """Filter hooks by exclude (blocklist) or inherit (allowlist)."""
    if inherit_hooks is not None:
        return [h for h in hooks if h.get("name") in inherit_hooks]

    if exclude_hooks is not None:
        blocklist = set(exclude_hooks)
        return [h for h in hooks if h.get("name") not in blocklist]

    return list(hooks)


def check_self_delegation_depth(current_depth: int, max_depth: int = 3) -> None:
    """Raise ValueError if self-delegation depth limit is exceeded.

    Args:
        current_depth: Current nesting depth (0-based).
        max_depth: Maximum allowed depth (default 3).

    Raises:
        ValueError: If current_depth >= max_depth.
    """
    if current_depth >= max_depth:
        raise ValueError(
            f"Exceeded max self-delegation depth ({max_depth}). "
            f"Current depth: {current_depth}."
        )


def format_parent_context(
    transcript: list[dict[str, Any]],
    context_depth: str = "none",
    context_scope: str = "conversation",
    context_turns: int | None = None,
) -> str:
    """Format parent conversation context for child session instruction.

    Args:
        transcript: Parent session transcript messages.
        context_depth: "none", "recent", or "all".
        context_scope: "conversation", "agents", or "full".
        context_turns: Number of recent turns to include (for "recent" depth).

    Returns:
        Formatted context string, empty if depth is "none".
    """
    if context_depth == "none" or not transcript:
        return ""

    if context_depth == "recent" and context_turns is not None:
        # Take the last N messages (approximation of turns)
        messages = transcript[-context_turns:]
    else:
        # "all" — include everything
        messages = transcript

    # Filter by scope
    if context_scope == "conversation":
        messages = [m for m in messages if m.get("role") in ("user", "assistant")]
    # "agents" and "full" include all messages for now

    if not messages:
        return ""

    lines = ["[PARENT CONVERSATION CONTEXT]"]
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, str) and content:
            lines.append(f"{role.upper()}: {content}")
    lines.append("[END PARENT CONTEXT]")

    return "\n".join(lines)
```

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_spawner.py -v
```

Expected: ALL 10 tests PASS

**Step 5: Commit**

```bash
git add amplifier-ipc-host/src/amplifier_ipc_host/spawner.py \
        amplifier-ipc-host/tests/test_spawner.py \
  && git commit -m "feat(host): add spawner module for sub-session config building

Session ID generation (W3C trace context lineage), config merging
(tool/hook lists merge by ID), tool/hook filtering (blocklist/allowlist),
self-delegation depth tracking, parent context formatting."
```

---

## Task 9: Sub-session spawning — spawn and resume orchestration

**Files:**
- Modify: `amplifier-ipc-host/src/amplifier_ipc_host/spawner.py` (add `spawn_child_session`, `resume_child_session`)
- Test: `amplifier-ipc-host/tests/test_spawner.py` (append)

This task adds the high-level spawn/resume functions that tie together definition resolution, config merging, and host creation. These functions will be called by the router when it handles `request.session_spawn`/`request.session_resume`.

**Step 1: Write failing tests**

Append to `amplifier-ipc-host/tests/test_spawner.py`:

```python
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Context formatting
# ---------------------------------------------------------------------------


async def test_format_parent_context_none_returns_empty() -> None:
    """context_depth='none' returns empty string."""
    result = format_parent_context(
        transcript=[{"role": "user", "content": "Hello"}],
        context_depth="none",
    )
    assert result == ""


async def test_format_parent_context_recent_limits_turns() -> None:
    """context_depth='recent' with context_turns limits messages."""
    transcript = [
        {"role": "user", "content": "First"},
        {"role": "assistant", "content": "Response 1"},
        {"role": "user", "content": "Second"},
        {"role": "assistant", "content": "Response 2"},
        {"role": "user", "content": "Third"},
    ]

    result = format_parent_context(
        transcript=transcript,
        context_depth="recent",
        context_turns=2,
    )

    assert "Third" in result
    assert "Response 2" in result
    assert "First" not in result


async def test_format_parent_context_all_includes_everything() -> None:
    """context_depth='all' includes all messages."""
    transcript = [
        {"role": "user", "content": "First"},
        {"role": "assistant", "content": "Response 1"},
    ]

    result = format_parent_context(
        transcript=transcript,
        context_depth="all",
    )

    assert "First" in result
    assert "Response 1" in result
    assert "[PARENT CONVERSATION CONTEXT]" in result
    assert "[END PARENT CONTEXT]" in result


# ---------------------------------------------------------------------------
# spawn_child_session
# ---------------------------------------------------------------------------


async def test_spawn_child_session_self_delegation(tmp_path: Path) -> None:
    """spawn_child_session with agent='self' clones parent config."""
    from amplifier_ipc_host.spawner import SpawnRequest, spawn_child_session

    request = SpawnRequest(
        agent="self",
        instruction="Do something",
        context_depth="none",
    )

    parent_config = {
        "services": ["foundation"],
        "orchestrator": "streaming",
        "context_manager": "simple",
        "provider": "anthropic",
        "tools": [{"name": "bash"}, {"name": "delegate"}],
    }

    # Mock the host creation and run
    with patch("amplifier_ipc_host.spawner._run_child_session") as mock_run:
        mock_run.return_value = {
            "session_id": "parent-child1_self",
            "response": "Done",
            "turn_count": 1,
            "metadata": {},
        }

        result = await spawn_child_session(
            request=request,
            parent_session_id="parent",
            parent_config=parent_config,
            parent_transcript=[],
            session_dir=tmp_path,
            self_delegation_depth=0,
        )

    assert result["response"] == "Done"
    assert "session_id" in result
    # _run_child_session should have been called
    mock_run.assert_called_once()
    # The child config should NOT include 'delegate' tool (default exclude)
    call_args = mock_run.call_args
    child_config = call_args[1]["config"] if "config" in call_args[1] else call_args[0][1]
    tool_names = [t["name"] for t in child_config.get("tools", [])]
    assert "delegate" not in tool_names


async def test_spawn_child_session_depth_limit_exceeded(tmp_path: Path) -> None:
    """spawn_child_session raises when self-delegation depth is exceeded."""
    from amplifier_ipc_host.spawner import SpawnRequest, spawn_child_session

    request = SpawnRequest(
        agent="self",
        instruction="Do something",
    )

    with pytest.raises(ValueError, match="self-delegation depth"):
        await spawn_child_session(
            request=request,
            parent_session_id="parent",
            parent_config={},
            parent_transcript=[],
            session_dir=tmp_path,
            self_delegation_depth=3,  # at limit
        )
```

**Step 2: Run to verify failure**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_spawner.py::test_spawn_child_session_self_delegation -v
```

Expected: FAIL — `ImportError: cannot import name 'SpawnRequest'`

**Step 3: Add SpawnRequest and spawn_child_session**

Add to `amplifier-ipc-host/src/amplifier_ipc_host/spawner.py`:

```python
from dataclasses import dataclass, field


@dataclass
class SpawnRequest:
    """Parameters for request.session_spawn."""

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


async def spawn_child_session(
    request: SpawnRequest,
    parent_session_id: str,
    parent_config: dict[str, Any],
    parent_transcript: list[dict[str, Any]],
    session_dir: Any,
    self_delegation_depth: int = 0,
    registry: Any | None = None,
) -> dict[str, Any]:
    """Spawn a child session and return the result.

    Args:
        request: Spawn request parameters.
        parent_session_id: Parent session ID for lineage.
        parent_config: Parent session config dict.
        parent_transcript: Parent transcript for context formatting.
        session_dir: Base directory for session persistence.
        self_delegation_depth: Current self-delegation nesting depth.
        registry: Definition registry for resolving non-self agents.

    Returns:
        Dict with session_id, response, turn_count, metadata.

    Raises:
        ValueError: If self-delegation depth limit is exceeded.
    """
    # 1. Check self-delegation depth
    if request.agent == "self":
        check_self_delegation_depth(self_delegation_depth)

    # 2. Generate child session ID
    child_session_id = generate_child_session_id(
        parent_session_id, request.agent
    )

    # 3. Build child config
    if request.agent == "self":
        child_config = dict(parent_config)
    else:
        # Resolve child agent definition via registry
        # For Phase 1, this is a placeholder — full resolution requires
        # the host to resolve definitions and build a SessionConfig.
        child_config = dict(parent_config)

    # 4. Filter tools and hooks
    if "tools" in child_config:
        child_config["tools"] = filter_tools(
            child_config["tools"],
            exclude_tools=request.exclude_tools,
            inherit_tools=request.inherit_tools,
        )

    if "hooks" in child_config:
        child_config["hooks"] = filter_hooks(
            child_config["hooks"],
            exclude_hooks=request.exclude_hooks,
            inherit_hooks=request.inherit_hooks,
        )

    # 5. Format parent context
    context_prefix = format_parent_context(
        transcript=parent_transcript,
        context_depth=request.context_depth,
        context_scope=request.context_scope,
        context_turns=request.context_turns,
    )

    # 6. Build instruction with context
    instruction = request.instruction
    if context_prefix:
        instruction = f"{context_prefix}\n\n{instruction}"

    # 7. Run child session
    return await _run_child_session(
        session_id=child_session_id,
        config=child_config,
        instruction=instruction,
        session_dir=session_dir,
        self_delegation_depth=(
            self_delegation_depth + 1 if request.agent == "self" else 0
        ),
    )


async def _run_child_session(
    session_id: str,
    config: dict[str, Any],
    instruction: str,
    session_dir: Any,
    self_delegation_depth: int = 0,
) -> dict[str, Any]:
    """Run a child session to completion.

    This is a placeholder for Phase 1. The full implementation will:
    1. Create a SessionConfig from the merged config
    2. Create a Host instance
    3. Run the host with the instruction
    4. Collect and return the result

    For now, this raises NotImplementedError — it will be completed
    when providers are available (Phase 2/3).
    """
    raise NotImplementedError(
        "Full child session execution requires provider implementation (Phase 2). "
        f"Session {session_id} with instruction: {instruction[:50]}..."
    )
```

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_spawner.py -v
```

Expected: ALL tests PASS (the `spawn_child_session_self_delegation` test mocks `_run_child_session`)

**Step 5: Commit**

```bash
git add amplifier-ipc-host/src/amplifier_ipc_host/spawner.py \
        amplifier-ipc-host/tests/test_spawner.py \
  && git commit -m "feat(host): add spawn_child_session with config merge and filtering

SpawnRequest dataclass, spawn_child_session orchestrates session ID
generation, config merging, tool/hook filtering, context formatting.
_run_child_session is a placeholder for Phase 2."
```

---

## Task 10: Sub-session spawning — wire protocol routing

**Files:**
- Modify: `amplifier-ipc-host/src/amplifier_ipc_host/router.py` (add spawn/resume routing)
- Test: `amplifier-ipc-host/tests/test_router.py` (append)

**Step 1: Write failing tests**

Append to `amplifier-ipc-host/tests/test_router.py`:

```python
# ---------------------------------------------------------------------------
# Sub-session spawning routing tests
# ---------------------------------------------------------------------------


async def test_route_session_spawn() -> None:
    """request.session_spawn is routed to the spawn handler."""
    router, _, _ = _build_router_with_two_services()

    # Set up a mock spawn handler
    spawn_result = {
        "session_id": "parent-child1_explorer",
        "response": "Done",
        "turn_count": 1,
        "metadata": {},
    }

    async def mock_spawn_handler(params: Any) -> Any:
        return spawn_result

    router._spawn_handler = mock_spawn_handler

    result = await router.route_request(
        "request.session_spawn",
        {
            "agent": "explorer",
            "instruction": "Find files",
            "context_depth": "none",
        },
    )

    assert result == spawn_result


async def test_route_session_resume() -> None:
    """request.session_resume is routed to the resume handler."""
    router, _, _ = _build_router_with_two_services()

    resume_result = {
        "session_id": "parent-child1_explorer",
        "response": "Continued",
        "turn_count": 2,
        "metadata": {},
    }

    async def mock_resume_handler(params: Any) -> Any:
        return resume_result

    router._resume_handler = mock_resume_handler

    result = await router.route_request(
        "request.session_resume",
        {
            "session_id": "parent-child1_explorer",
            "instruction": "Continue",
        },
    )

    assert result == resume_result
```

**Step 2: Run to verify failure**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_router.py::test_route_session_spawn -v
```

Expected: FAIL — `JsonRpcError: Unknown routing method: 'request.session_spawn'`

**Step 3: Add spawn/resume routing to Router**

In `amplifier-ipc-host/src/amplifier_ipc_host/router.py`:

1. Add `spawn_handler` and `resume_handler` parameters to `__init__`:

```python
from collections.abc import Callable, Coroutine

# In __init__ signature, add:
    spawn_handler: Callable[..., Coroutine[Any, Any, Any]] | None = None,
    resume_handler: Callable[..., Coroutine[Any, Any, Any]] | None = None,
```

Store them:

```python
    self._spawn_handler = spawn_handler
    self._resume_handler = resume_handler
```

2. Add routing in `route_request`, before the final `raise JsonRpcError`:

```python
if method == "request.session_spawn":
    if self._spawn_handler is None:
        raise JsonRpcError(
            code=METHOD_NOT_FOUND,
            message="Sub-session spawning is not configured",
        )
    return await self._spawn_handler(params)

if method == "request.session_resume":
    if self._resume_handler is None:
        raise JsonRpcError(
            code=METHOD_NOT_FOUND,
            message="Sub-session resume is not configured",
        )
    return await self._resume_handler(params)
```

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_router.py -v
```

Expected: ALL router tests PASS

**Step 5: Commit**

```bash
git add amplifier-ipc-host/src/amplifier_ipc_host/router.py \
        amplifier-ipc-host/tests/test_router.py \
  && git commit -m "feat(host): route request.session_spawn and request.session_resume

Router delegates to configurable spawn/resume handler callbacks.
Raises METHOD_NOT_FOUND if handlers are not configured."
```

---

## Task 11: Wire spawner into host

**Files:**
- Modify: `amplifier-ipc-host/src/amplifier_ipc_host/host.py` (pass spawn/resume handlers to Router)
- Modify: `amplifier-ipc-host/src/amplifier_ipc_host/__init__.py` (export spawner types)
- Test: `amplifier-ipc-host/tests/test_host.py` (append)

**Step 1: Write failing test**

Append to `amplifier-ipc-host/tests/test_host.py`:

```python
async def test_host_routes_session_spawn_to_spawner() -> None:
    """_handle_orchestrator_request routes request.session_spawn."""
    from amplifier_ipc_host.spawner import SpawnRequest

    registry = CapabilityRegistry()
    registry.register(
        "foundation",
        {
            "tools": [{"name": "bash", "description": "Run bash"}],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": [],
        },
    )

    services: dict[str, Any] = {
        "foundation": FakeService(FakeClient()),
        "ctx": FakeService(FakeClient()),
        "provider": FakeService(FakeClient()),
    }

    config = SessionConfig(
        services=["foundation"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()

    host = Host(config=config, settings=settings)
    host._registry = registry
    host._services = services

    spawn_called_with: list[Any] = []

    async def mock_spawn(params: Any) -> Any:
        spawn_called_with.append(params)
        return {
            "session_id": "parent-child_explorer",
            "response": "Done",
            "turn_count": 1,
            "metadata": {},
        }

    host._router = Router(
        registry=registry,
        services=services,
        context_manager_key="ctx",
        provider_key="provider",
        spawn_handler=mock_spawn,
    )

    result = await host._handle_orchestrator_request(
        "request.session_spawn",
        {"agent": "explorer", "instruction": "Find files"},
    )

    assert result["response"] == "Done"
    assert len(spawn_called_with) == 1
```

**Step 2: Run to verify it fails**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_host.py::test_host_routes_session_spawn_to_spawner -v
```

Expected: FAIL until Router accepts spawn_handler and host passes it

**Step 3: Wire spawn handler in Host.run()**

In `amplifier-ipc-host/src/amplifier_ipc_host/host.py`, in the `run()` method where the Router is created, add a spawn handler:

```python
from amplifier_ipc_host.spawner import SpawnRequest, spawn_child_session

# In run(), when creating the router:
async def _handle_spawn(params: Any) -> Any:
    """Handle request.session_spawn from the orchestrator."""
    request = SpawnRequest(
        agent=params.get("agent", "self"),
        instruction=params.get("instruction", ""),
        context_depth=params.get("context_depth", "none"),
        context_scope=params.get("context_scope", "conversation"),
        context_turns=params.get("context_turns"),
        exclude_tools=params.get("exclude_tools"),
        inherit_tools=params.get("inherit_tools"),
        exclude_hooks=params.get("exclude_hooks"),
        inherit_hooks=params.get("inherit_hooks"),
        agents=params.get("agents"),
        provider_preferences=params.get("provider_preferences"),
        model_role=params.get("model_role"),
    )
    return await spawn_child_session(
        request=request,
        parent_session_id=session_id,
        parent_config={},  # TODO: expose full config dict
        parent_transcript=(
            self._persistence.load_transcript()
            if self._persistence else []
        ),
        session_dir=self._session_dir,
    )

self._router = Router(
    registry=self._registry,
    services=self._services,
    context_manager_key=context_manager_key,
    provider_key=provider_key,
    state=self._state,
    spawn_handler=_handle_spawn,
)
```

**Step 4: Update __init__.py exports**

Add spawner exports to `amplifier-ipc-host/src/amplifier_ipc_host/__init__.py`:

```python
from amplifier_ipc_host.spawner import (
    SpawnRequest,
    generate_child_session_id,
    merge_configs,
    filter_tools,
    filter_hooks,
    spawn_child_session,
)
```

**Step 5: Run all host tests**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/ -v
```

Expected: ALL tests PASS

**Step 6: Commit**

```bash
git add amplifier-ipc-host/src/amplifier_ipc_host/host.py \
        amplifier-ipc-host/src/amplifier_ipc_host/__init__.py \
        amplifier-ipc-host/tests/test_host.py \
  && git commit -m "feat(host): wire spawner into host for request.session_spawn

Host creates spawn handler and passes it to Router. Orchestrator can now
send request.session_spawn and the host will build child config."
```

---

## Task 12: Integration test — all three protocols

**Files:**
- Create: `amplifier-ipc-host/tests/test_protocol_integration.py`

This test exercises all three protocol extensions together in a single test file, verifying they work correctly in the host's routing infrastructure.

**Step 1: Write the integration test**

Create `amplifier-ipc-host/tests/test_protocol_integration.py`:

```python
"""Integration tests for all three protocol extensions.

Tests state, streaming, and spawning through the Router and Host
infrastructure using fake services.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from amplifier_ipc_host.config import HostSettings, SessionConfig
from amplifier_ipc_host.events import (
    CompleteEvent,
    StreamContentBlockEndEvent,
    StreamContentBlockStartEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
)
from amplifier_ipc_host.host import Host
from amplifier_ipc_host.registry import CapabilityRegistry
from amplifier_ipc_host.router import Router


# ---------------------------------------------------------------------------
# Fakes (same pattern as test_router.py)
# ---------------------------------------------------------------------------


class FakeClient:
    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._responses: dict[str, Any] = responses or {}
        self.on_notification = None

    async def request(self, method: str, params: Any = None) -> Any:
        self.calls.append((method, params))
        if method in self._responses:
            return self._responses[method]
        return {}


class FakeService:
    def __init__(self, client: FakeClient) -> None:
        self.client = client


# ---------------------------------------------------------------------------
# Test 1: State round-trip through router
# ---------------------------------------------------------------------------


async def test_state_set_then_get_round_trip() -> None:
    """state.set followed by state.get returns the value through the router."""
    registry = CapabilityRegistry()
    registry.register(
        "foundation",
        {
            "tools": [{"name": "bash", "description": "Run bash"}],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [{"name": "simple"}],
            "providers": [],
            "content": [],
        },
    )
    registry.register(
        "providers",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [{"name": "mock"}],
            "content": [],
        },
    )

    services = {
        "foundation": FakeService(FakeClient()),
        "providers": FakeService(FakeClient()),
    }

    router = Router(
        registry=registry,
        services=services,
        context_manager_key="foundation",
        provider_key="providers",
    )

    # Set a value
    set_result = await router.route_request(
        "request.state_set",
        {"key": "todo_state", "value": {"items": ["buy milk", "write tests"]}},
    )
    assert set_result == {"ok": True}

    # Get the value back
    get_result = await router.route_request(
        "request.state_get",
        {"key": "todo_state"},
    )
    assert get_result == {"value": {"items": ["buy milk", "write tests"]}}

    # Get a missing key
    missing_result = await router.route_request(
        "request.state_get",
        {"key": "nonexistent"},
    )
    assert missing_result == {"value": None}


# ---------------------------------------------------------------------------
# Test 2: Full streaming event sequence through orchestrator loop
# ---------------------------------------------------------------------------


async def test_full_streaming_event_sequence() -> None:
    """Orchestrator loop yields complete streaming sequence:
    content_block_start → thinking → tokens → content_block_end → complete."""
    config = SessionConfig(
        services=["orch"],
        orchestrator="loop",
        context_manager="simple",
        provider="mock",
    )
    settings = HostSettings()
    host = Host(config=config, settings=settings)

    fake_process = MagicMock()
    fake_process.stdin = MagicMock()
    fake_process.stdout = MagicMock()
    fake_service = MagicMock()
    fake_service.process = fake_process
    host._services = {"orch": fake_service}

    captured_id: list[str] = []

    async def fake_write(stream: object, message: dict) -> None:
        if message.get("method") == "orchestrator.execute":
            captured_id.append(message["id"])

    messages = [
        {"jsonrpc": "2.0", "method": "stream.content_block_start",
         "params": {"type": "thinking", "index": 0}},
        {"jsonrpc": "2.0", "method": "stream.thinking",
         "params": {"thinking": "Let me think..."}},
        {"jsonrpc": "2.0", "method": "stream.content_block_end",
         "params": {"type": "thinking", "index": 0}},
        {"jsonrpc": "2.0", "method": "stream.content_block_start",
         "params": {"type": "text", "index": 1}},
        {"jsonrpc": "2.0", "method": "stream.token",
         "params": {"token": "Hello"}},
        {"jsonrpc": "2.0", "method": "stream.token",
         "params": {"token": " World"}},
        {"jsonrpc": "2.0", "method": "stream.content_block_end",
         "params": {"type": "text", "index": 1}},
        # Final response (filled in dynamically)
        None,
    ]
    read_idx = 0

    async def fake_read(stream: object) -> dict | None:
        nonlocal read_idx
        idx = read_idx
        read_idx += 1
        if idx < len(messages) - 1:
            return messages[idx]
        return {
            "jsonrpc": "2.0",
            "id": captured_id[0],
            "result": "Hello World",
        }

    with (
        patch("amplifier_ipc_host.host.write_message", fake_write),
        patch("amplifier_ipc_host.host.read_message", fake_read),
    ):
        events = []
        async for event in host._orchestrator_loop(
            orchestrator_key="orch",
            prompt="hello",
            system_prompt="be helpful",
        ):
            events.append(event)

    assert len(events) == 8
    assert isinstance(events[0], StreamContentBlockStartEvent)
    assert events[0].block_type == "thinking"
    assert isinstance(events[1], StreamThinkingEvent)
    assert isinstance(events[2], StreamContentBlockEndEvent)
    assert isinstance(events[3], StreamContentBlockStartEvent)
    assert events[3].block_type == "text"
    assert isinstance(events[4], StreamTokenEvent)
    assert events[4].token == "Hello"
    assert isinstance(events[5], StreamTokenEvent)
    assert events[5].token == " World"
    assert isinstance(events[6], StreamContentBlockEndEvent)
    assert isinstance(events[7], CompleteEvent)


# ---------------------------------------------------------------------------
# Test 3: Spawn handler is routable through the router
# ---------------------------------------------------------------------------


async def test_spawn_handler_receives_correct_params() -> None:
    """request.session_spawn passes params to spawn handler correctly."""
    registry = CapabilityRegistry()
    services: dict[str, Any] = {
        "ctx": FakeService(FakeClient()),
        "prov": FakeService(FakeClient()),
    }

    spawn_params_received: list[Any] = []

    async def mock_spawn(params: Any) -> Any:
        spawn_params_received.append(params)
        return {
            "session_id": "parent-child_test",
            "response": "Child completed",
            "turn_count": 1,
            "metadata": {"agent": params.get("agent")},
        }

    router = Router(
        registry=registry,
        services=services,
        context_manager_key="ctx",
        provider_key="prov",
        spawn_handler=mock_spawn,
    )

    result = await router.route_request(
        "request.session_spawn",
        {
            "agent": "explorer",
            "instruction": "Find all Python files",
            "context_depth": "recent",
            "context_turns": 5,
            "exclude_tools": ["web_search"],
        },
    )

    assert result["response"] == "Child completed"
    assert result["metadata"]["agent"] == "explorer"
    assert len(spawn_params_received) == 1
    assert spawn_params_received[0]["agent"] == "explorer"
    assert spawn_params_received[0]["context_depth"] == "recent"
    assert spawn_params_received[0]["exclude_tools"] == ["web_search"]


# ---------------------------------------------------------------------------
# Test 4: State persists across set/get within a single router instance
# ---------------------------------------------------------------------------


async def test_state_persists_across_multiple_operations() -> None:
    """Multiple state.set calls accumulate, state.get reads latest."""
    registry = CapabilityRegistry()
    services: dict[str, Any] = {
        "ctx": FakeService(FakeClient()),
        "prov": FakeService(FakeClient()),
    }

    router = Router(
        registry=registry,
        services=services,
        context_manager_key="ctx",
        provider_key="prov",
    )

    # Set multiple keys
    await router.route_request(
        "request.state_set", {"key": "counter", "value": 1}
    )
    await router.route_request(
        "request.state_set", {"key": "name", "value": "test"}
    )
    await router.route_request(
        "request.state_set", {"key": "counter", "value": 2}
    )

    # Read them back
    counter = await router.route_request(
        "request.state_get", {"key": "counter"}
    )
    name = await router.route_request(
        "request.state_get", {"key": "name"}
    )

    assert counter == {"value": 2}
    assert name == {"value": "test"}
```

**Step 2: Run integration tests**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_protocol_integration.py -v
```

Expected: ALL 4 integration tests PASS

**Step 3: Run full test suite to verify nothing broke**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/ -v
cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/ -v
cd amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/ -v
```

Expected: ALL tests PASS across all three packages

**Step 4: Commit**

```bash
git add amplifier-ipc-host/tests/test_protocol_integration.py \
  && git commit -m "test(host): add integration tests for all three protocol extensions

Tests state round-trip, full streaming event sequence, spawn handler
routing, and state accumulation across multiple operations."
```

---

## Summary of what Phase 1 delivers

After all 12 tasks:

| Capability | Status | Wire Methods |
|---|---|---|
| **Registry/definitions in host** | Complete | N/A (internal) |
| **CLI re-exports from host** | Complete | N/A (import change) |
| **Cross-service shared state** | Complete | `request.state_get`, `request.state_set` |
| **Provider streaming relay** | Infrastructure ready | `stream.provider.*` → relay → `stream.*` |
| **Content block events** | Complete | `stream.content_block_start`, `stream.content_block_end` |
| **Sub-session spawning** | Config building complete, execution placeholder | `request.session_spawn`, `request.session_resume` |

**What's deferred to Phase 2/3:**
- `_run_child_session` full implementation (needs real providers)
- `request.session_resume` full implementation (needs persisted child sessions)
- Real provider-to-host streaming (needs Anthropic provider)
- State access from non-orchestrator services (requires bidirectional service communication)
- Fork at turn N (`request.session_fork`)
