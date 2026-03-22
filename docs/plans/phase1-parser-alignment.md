# Phase 1: Parser Alignment Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Update all parser code (dataclasses, parsers, registry, discover, session launcher) to read the new nested definition file format specified in `docs/specs/definition-files.md`. Additionally, implement the component configuration protocol: `scan_package()` returns classes instead of instances, `Server` supports a `configure` method for lazy component instantiation with config, and the host sends `configure` after `describe` in the startup sequence.

**Architecture:** The old format uses flat YAML with `type: agent`, `local_ref`, plural `services:` (list of dicts with `name`/`installer`/`source`). The new format uses nested `agent:` or `behavior:` as the top-level YAML key, `ref` instead of `local_ref`, and singular `service:` with `stack`/`source`/`command` fields. All parsers, dataclasses, and registry code must be updated to read the new format. Existing tests must be rewritten to use the new format in their YAML fixtures.

**Tech Stack:** Python 3.11+, pytest, dataclasses, PyYAML, Click

---

### Task 1: Update ServiceEntry dataclass

**Files:**
- Modify: `src/amplifier_ipc/host/definitions.py:37-44`
- Test: `tests/host/test_definitions.py`

**Step 1: Write the failing test**

Open `tests/host/test_definitions.py` and add this test at the end of the file:

```python
def test_service_entry_has_stack_and_command_fields() -> None:
    """ServiceEntry must have stack, source, and command fields (not name/installer)."""
    from amplifier_ipc.host.definitions import ServiceEntry

    svc = ServiceEntry(stack="uv", source="git+https://example.com/pkg", command="my-serve")
    assert svc.stack == "uv"
    assert svc.source == "git+https://example.com/pkg"
    assert svc.command == "my-serve"
    # Must NOT have a 'name' or 'installer' attribute
    assert not hasattr(svc, "name"), "ServiceEntry should not have a 'name' field"
    assert not hasattr(svc, "installer"), "ServiceEntry should not have an 'installer' field"
```

**Step 2: Run test to verify it fails**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_definitions.py::test_service_entry_has_stack_and_command_fields -v
```
Expected: FAIL — `ServiceEntry` currently takes `name` as its first arg, doesn't have `stack` or `command`.

**Step 3: Write minimal implementation**

In `src/amplifier_ipc/host/definitions.py`, replace the `ServiceEntry` dataclass (lines 37-44):

```python
@dataclass
class ServiceEntry:
    """Represents the service block from a definition file."""

    stack: str | None = None
    source: str | None = None
    command: str | None = None
```

**Step 4: Run test to verify it passes**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_definitions.py::test_service_entry_has_stack_and_command_fields -v
```
Expected: PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/definitions.py tests/host/test_definitions.py && git commit -m "refactor: update ServiceEntry dataclass — stack/source/command instead of name/installer"
```

---

### Task 2: Update AgentDefinition and BehaviorDefinition dataclasses

**Files:**
- Modify: `src/amplifier_ipc/host/definitions.py:46-81`
- Test: `tests/host/test_definitions.py`

**Step 1: Write the failing test**

Add to `tests/host/test_definitions.py`:

```python
def test_agent_definition_has_ref_not_local_ref() -> None:
    """AgentDefinition must have 'ref' (not 'local_ref') and singular 'service' (not 'services')."""
    from amplifier_ipc.host.definitions import AgentDefinition, ServiceEntry

    agent = AgentDefinition(ref="my-agent", uuid="00000000-0000-0000-0000-000000000000")
    assert agent.ref == "my-agent"
    assert not hasattr(agent, "local_ref"), "Should use 'ref', not 'local_ref'"
    assert not hasattr(agent, "type"), "Should not have 'type' field"
    assert not hasattr(agent, "services"), "Should use singular 'service', not 'services'"
    # 'service' should accept a ServiceEntry or None
    assert agent.service is None


def test_behavior_definition_has_ref_not_local_ref() -> None:
    """BehaviorDefinition must have 'ref' (not 'local_ref') and singular 'service'."""
    from amplifier_ipc.host.definitions import BehaviorDefinition

    behav = BehaviorDefinition(ref="my-behavior", uuid="11111111-0000-0000-0000-000000000000")
    assert behav.ref == "my-behavior"
    assert not hasattr(behav, "local_ref"), "Should use 'ref', not 'local_ref'"
    assert not hasattr(behav, "type"), "Should not have 'type' field"
    assert not hasattr(behav, "services"), "Should use singular 'service', not 'services'"
    assert behav.service is None
    # component_config should default to empty dict
    assert behav.component_config == {}
```

**Step 2: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_definitions.py::test_agent_definition_has_ref_not_local_ref tests/host/test_definitions.py::test_behavior_definition_has_ref_not_local_ref -v
```
Expected: FAIL — current classes have `local_ref`, `type`, `services`.

**Step 3: Write minimal implementation**

In `src/amplifier_ipc/host/definitions.py`, replace the `AgentDefinition` and `BehaviorDefinition` dataclasses:

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

Key changes:
- `local_ref` → `ref`
- Removed `type` field (the wrapper key tells us the type)
- `services: list[ServiceEntry]` → `service: ServiceEntry | None`
- `tools`/`hooks`/`agents`/`context` are now `bool` (the spec uses boolean flags, not lists)
- `behaviors` is now `list[dict[str, str]]` (list of `{alias: url}` dicts, preserving alias info)
- Both dataclasses get `component_config: dict[str, Any]` to hold parsed `config:` block from YAML

**Step 4: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_definitions.py::test_agent_definition_has_ref_not_local_ref tests/host/test_definitions.py::test_behavior_definition_has_ref_not_local_ref -v
```
Expected: PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/definitions.py tests/host/test_definitions.py && git commit -m "refactor: update AgentDefinition/BehaviorDefinition — ref, singular service, bool capabilities"
```

---

### Task 3: Rewrite `_parse_services()` → `_parse_service()` and update parsers

**Files:**
- Modify: `src/amplifier_ipc/host/definitions.py:132-221`
- Test: `tests/host/test_definitions.py`

**Step 1: Write the failing tests**

Replace **all existing** `test_parse_agent_definition_*` and `test_parse_behavior_definition_*` tests in `tests/host/test_definitions.py` with the following new-format tests. Also remove the old `_to_str_list` tests and the `test_relative_source_resolved_against_definition_dir` test (they test old-format concepts). Keep the `resolve_agent` tests for now (they'll be updated in Task 5).

Add these tests (replacing old parse tests):

```python
# ---------------------------------------------------------------------------
# _parse_service unit tests
# ---------------------------------------------------------------------------


def test_parse_service_returns_service_entry() -> None:
    """_parse_service() returns a ServiceEntry from a dict."""
    from amplifier_ipc.host.definitions import _parse_service

    result = _parse_service({
        "stack": "uv",
        "source": "git+https://example.com/pkg",
        "command": "my-serve",
    })
    assert result is not None
    assert result.stack == "uv"
    assert result.source == "git+https://example.com/pkg"
    assert result.command == "my-serve"


def test_parse_service_returns_none_for_none() -> None:
    """_parse_service(None) returns None."""
    from amplifier_ipc.host.definitions import _parse_service

    assert _parse_service(None) is None


# ---------------------------------------------------------------------------
# parse_agent_definition tests (new nested format)
# ---------------------------------------------------------------------------


def test_parse_agent_definition_nested_format() -> None:
    """parse_agent_definition() reads from nested agent: wrapper."""
    yaml_content = """\
agent:
  ref: my-agent
  uuid: 12345678-abcd-ef00-0000-000000000000
  version: 1
  description: A test agent
  orchestrator: streaming
  context_manager: simple
  provider: providers:anthropic
  tools: true
  hooks: true
  agents: true
  context: true
  behaviors:
    - modes: https://example.com/modes.yaml
    - skills: https://example.com/skills.yaml
  service:
    stack: uv
    source: git+https://example.com/foundation
    command: my-serve
"""
    result = parse_agent_definition(yaml_content)

    assert isinstance(result, AgentDefinition)
    assert result.ref == "my-agent"
    assert result.uuid == "12345678-abcd-ef00-0000-000000000000"
    assert result.version == "1"
    assert result.description == "A test agent"
    assert result.orchestrator == "streaming"
    assert result.context_manager == "simple"
    assert result.provider == "providers:anthropic"
    assert result.tools is True
    assert result.hooks is True
    assert result.agents is True
    assert result.context is True
    assert result.behaviors == [
        {"modes": "https://example.com/modes.yaml"},
        {"skills": "https://example.com/skills.yaml"},
    ]
    assert result.service is not None
    assert result.service.stack == "uv"
    assert result.service.source == "git+https://example.com/foundation"
    assert result.service.command == "my-serve"


def test_parse_agent_definition_no_service() -> None:
    """parse_agent_definition() handles agents with no service block."""
    yaml_content = """\
agent:
  ref: minimal-agent
  uuid: 00000000-0000-0000-0000-000000000001
  tools: false
  hooks: false
"""
    result = parse_agent_definition(yaml_content)
    assert result.ref == "minimal-agent"
    assert result.service is None
    assert result.tools is False
    assert result.hooks is False


def test_parse_agent_definition_empty_behaviors() -> None:
    """parse_agent_definition() handles empty behaviors list."""
    yaml_content = """\
agent:
  ref: no-behaviors
  uuid: 00000000-0000-0000-0000-000000000002
  behaviors: []
"""
    result = parse_agent_definition(yaml_content)
    assert result.behaviors == []


# ---------------------------------------------------------------------------
# parse_behavior_definition tests (new nested format)
# ---------------------------------------------------------------------------


def test_parse_behavior_definition_nested_format() -> None:
    """parse_behavior_definition() reads from nested behavior: wrapper."""
    yaml_content = """\
behavior:
  ref: modes
  uuid: 6d239fcc-e53b-4a6d-a81c-3b3a5a8fc139
  version: 1
  description: Generic mode system
  tools: true
  hooks: true
  context: true
  behaviors: []
  service:
    stack: uv
    source: git+https://example.com/modes
    command: amplifier-modes-serve
"""
    result = parse_behavior_definition(yaml_content)

    assert isinstance(result, BehaviorDefinition)
    assert result.ref == "modes"
    assert result.uuid == "6d239fcc-e53b-4a6d-a81c-3b3a5a8fc139"
    assert result.version == "1"
    assert result.description == "Generic mode system"
    assert result.tools is True
    assert result.hooks is True
    assert result.context is True
    assert result.behaviors == []
    assert result.service is not None
    assert result.service.stack == "uv"
    assert result.service.command == "amplifier-modes-serve"


def test_parse_behavior_definition_no_service() -> None:
    """parse_behavior_definition() handles content-only behaviors (no service block)."""
    yaml_content = """\
behavior:
  ref: content-only
  uuid: aaaaaaaa-0000-0000-0000-000000000000
  context: true
"""
    result = parse_behavior_definition(yaml_content)
    assert result.ref == "content-only"
    assert result.service is None
    assert result.context is True


def test_parse_agent_definition_with_config() -> None:
    """parse_agent_definition() reads config: block into component_config."""
    yaml_content = """\
agent:
  ref: configured-agent
  uuid: 00000000-0000-0000-0000-000000000003
  config:
    streaming:
      max_iterations: 50
    modes:mode-tool:
      gate_policy: block
"""
    result = parse_agent_definition(yaml_content)
    assert result.component_config == {
        "streaming": {"max_iterations": 50},
        "modes:mode-tool": {"gate_policy": "block"},
    }


def test_parse_behavior_definition_with_config() -> None:
    """parse_behavior_definition() reads config: block into component_config."""
    yaml_content = """\
behavior:
  ref: configured-behavior
  uuid: 00000000-0000-0000-0000-000000000004
  tools: true
  hooks: true
  config:
    mode-tool:
      gate_policy: warn
    mode-hooks:
      search_paths: []
"""
    result = parse_behavior_definition(yaml_content)
    assert result.component_config == {
        "mode-tool": {"gate_policy": "warn"},
        "mode-hooks": {"search_paths": []},
    }


def test_parse_behavior_definition_with_sub_behaviors() -> None:
    """parse_behavior_definition() preserves nested behavior alias-url dicts."""
    yaml_content = """\
behavior:
  ref: parent
  uuid: bbbbbbbb-0000-0000-0000-000000000000
  behaviors:
    - child-a: https://example.com/child-a.yaml
    - child-b: https://example.com/child-b.yaml
"""
    result = parse_behavior_definition(yaml_content)
    assert result.behaviors == [
        {"child-a": "https://example.com/child-a.yaml"},
        {"child-b": "https://example.com/child-b.yaml"},
    ]
```

**Step 2: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_definitions.py::test_parse_service_returns_service_entry tests/host/test_definitions.py::test_parse_agent_definition_nested_format tests/host/test_definitions.py::test_parse_behavior_definition_nested_format -v
```
Expected: FAIL — `_parse_service` doesn't exist, parsers read flat format.

**Step 3: Write minimal implementation**

In `src/amplifier_ipc/host/definitions.py`:

1. **Delete** the `_to_str_list()` function (lines 94-115), the `_to_dict()` function (lines 118-129), and the `_parse_services()` function (lines 132-156).

2. **Add** the new `_parse_service()` function:

```python
def _parse_service(service_data: Any) -> ServiceEntry | None:
    """Parse a service dict into a ServiceEntry.

    Args:
        service_data: Raw YAML data for the singular service block (dict or None).

    Returns:
        ServiceEntry if service_data is a dict, None otherwise.
    """
    if not isinstance(service_data, dict):
        return None
    return ServiceEntry(
        stack=service_data.get("stack"),
        source=service_data.get("source"),
        command=service_data.get("command"),
    )
```

3. **Replace** `parse_agent_definition()`:

```python
def parse_agent_definition(yaml_content: str) -> AgentDefinition:
    """Parse a YAML string into an AgentDefinition.

    Expects the new nested format with `agent:` as the top-level key.

    Args:
        yaml_content: YAML text of an agent definition file.

    Returns:
        AgentDefinition populated from the YAML content.
    """
    data: dict[str, Any] = yaml.safe_load(yaml_content) or {}
    inner = data.get("agent", {})

    behaviors_raw = inner.get("behaviors") or []
    # Normalize: keep list of single-key dicts as-is
    behaviors = []
    if isinstance(behaviors_raw, list):
        for item in behaviors_raw:
            if isinstance(item, dict):
                behaviors.append(dict(item))
            elif isinstance(item, str):
                behaviors.append(item)

    return AgentDefinition(
        ref=inner.get("ref"),
        uuid=inner.get("uuid"),
        version=str(inner["version"]) if inner.get("version") is not None else None,
        description=inner.get("description"),
        orchestrator=inner.get("orchestrator"),
        context_manager=inner.get("context_manager"),
        provider=inner.get("provider"),
        tools=bool(inner.get("tools", False)),
        hooks=bool(inner.get("hooks", False)),
        agents=bool(inner.get("agents", False)),
        context=bool(inner.get("context", False)),
        behaviors=behaviors,
        service=_parse_service(inner.get("service")),
        component_config=inner.get("component_config") or {},
    )
```

4. **Replace** `parse_behavior_definition()`:

```python
def parse_behavior_definition(yaml_content: str) -> BehaviorDefinition:
    """Parse a YAML string into a BehaviorDefinition.

    Expects the new nested format with `behavior:` as the top-level key.

    Args:
        yaml_content: YAML text of a behavior definition file.

    Returns:
        BehaviorDefinition populated from the YAML content.
    """
    data: dict[str, Any] = yaml.safe_load(yaml_content) or {}
    inner = data.get("behavior", {})

    behaviors_raw = inner.get("behaviors") or []
    behaviors = []
    if isinstance(behaviors_raw, list):
        for item in behaviors_raw:
            if isinstance(item, dict):
                behaviors.append(dict(item))
            elif isinstance(item, str):
                behaviors.append(item)

    return BehaviorDefinition(
        ref=inner.get("ref"),
        uuid=inner.get("uuid"),
        version=str(inner["version"]) if inner.get("version") is not None else None,
        description=inner.get("description"),
        tools=bool(inner.get("tools", False)),
        hooks=bool(inner.get("hooks", False)),
        context=bool(inner.get("context", False)),
        behaviors=behaviors,
        service=_parse_service(inner.get("service")),
        component_config=inner.get("config") or {},
    )
```

5. **Remove** the `path` parameter from `parse_agent_definition()`. The new format uses `git+` URLs (never relative paths), so path resolution is no longer needed.

**Step 4: Run all new parse tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_definitions.py -k "test_parse_" -v
```
Expected: All new `test_parse_*` tests PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/definitions.py tests/host/test_definitions.py && git commit -m "refactor: rewrite parsers for nested agent:/behavior: format with singular service"
```

---

### Task 4: Update `scan_location()` and `_try_parse_definition()`

**Files:**
- Modify: `src/amplifier_ipc/cli/commands/discover.py:25-53`
- Test: `tests/cli/test_commands/test_discover.py`

**Step 1: Write the failing test**

In `tests/cli/test_commands/test_discover.py`, replace the fixture definitions at the top (the `agent_yaml_content` and `behavior_yaml_content` fixtures) with new-format fixtures, and update all tests that use them:

Replace the two fixtures:

```python
@pytest.fixture()
def agent_yaml_content() -> str:
    return """\
agent:
  ref: my-agent
  uuid: 12345678-abcd-efgh-ijkl-mnopqrstuvwx
  description: A test agent definition
"""


@pytest.fixture()
def behavior_yaml_content() -> str:
    return """\
behavior:
  ref: my-behavior
  uuid: 87654321-dcba-hgfe-lkji-xwvutsrqponm
  description: A test behavior definition
"""
```

Update all test assertions from `item["local_ref"]` to `item["ref"]`:

- In `TestScanLocationFindsAgentYaml`: change `assert item["local_ref"] == "my-agent"` → `assert item["ref"] == "my-agent"`
- In `TestScanLocationFindsBehaviorYaml`: change `assert item["local_ref"] == "my-behavior"` → `assert item["ref"] == "my-behavior"`
- In `TestScanLocationEmptyDirectory.test_scan_location_ignores_non_definition_yaml`: no change needed (YAML has no `agent:` or `behavior:` key).

**Step 2: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/cli/test_commands/test_discover.py::TestScanLocationFindsAgentYaml -v
```
Expected: FAIL — `scan_location` still checks for `parsed.get("type")`.

**Step 3: Write minimal implementation**

In `src/amplifier_ipc/cli/commands/discover.py`, replace `_try_parse_definition()`:

```python
def _try_parse_definition(yaml_path: Path, results: list[dict[str, Any]]) -> None:
    """Parse a YAML file and append to results if it is an agent or behavior definition.

    Recognizes the new nested format: files with `agent:` or `behavior:` as a
    top-level YAML key are treated as definitions.

    Args:
        yaml_path: Path to the YAML file to parse.
        results: List to append matching definitions to.
    """
    try:
        raw_content = yaml_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw_content)
    except Exception:
        return

    if not isinstance(parsed, dict):
        return

    # Detect definition type from top-level key
    if "agent" in parsed:
        def_type = "agent"
        inner = parsed["agent"] if isinstance(parsed["agent"], dict) else {}
    elif "behavior" in parsed:
        def_type = "behavior"
        inner = parsed["behavior"] if isinstance(parsed["behavior"], dict) else {}
    else:
        return

    ref = inner.get("ref", "")
    results.append(
        {
            "type": def_type,
            "ref": ref,
            "path": str(yaml_path.resolve()),
            "raw_content": raw_content,
        }
    )
```

Also update the `discover()` Click command's display line (line ~184) to use `ref` instead of `local_ref`:

```python
        for item in definitions:
            console.print(
                f"  [{item['type']}] {item['ref'] or '(no ref)'}"
                f"  {item['path']}"
            )
```

And the register output line (~195):

```python
            console.print(
                f"[blue]Registered[/blue] {item['type']} '{item['ref']}'"
            )
```

**Step 4: Run all discover tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/cli/test_commands/test_discover.py -v
```
Expected: All PASS. Note: `TestDiscoverWithRegister` may fail because `register_definition()` hasn't been updated yet. If so, that's expected — it will be fixed in Task 5. You can skip it for now and verify it later.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/cli/commands/discover.py tests/cli/test_commands/test_discover.py && git commit -m "refactor: scan_location detects agent:/behavior: top-level keys instead of type:"
```

---

### Task 5: Update `register_definition()` in the Registry

**Files:**
- Modify: `src/amplifier_ipc/host/definition_registry.py:60-135`
- Test: `tests/host/test_definition_registry.py`

**Step 1: Write the failing tests**

In `tests/host/test_definition_registry.py`, update all test YAML content and assertions. Replace the entire file content with:

```python
"""Tests for the definition registry (Registry class managing $AMPLIFIER_HOME layout)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from amplifier_ipc.host.definition_registry import Registry


def test_ensure_home_creates_structure(tmp_path: Path) -> None:
    """ensure_home() creates the expected directory structure and alias files."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    home = registry.home
    assert home.is_dir()
    assert (home / "definitions").is_dir()
    assert (home / "environments").is_dir()
    assert (home / "agents.yaml").is_file()
    assert (home / "behaviors.yaml").is_file()

    agents_data = yaml.safe_load((home / "agents.yaml").read_text())
    behaviors_data = yaml.safe_load((home / "behaviors.yaml").read_text())
    assert agents_data == {} or agents_data is None
    assert behaviors_data == {} or behaviors_data is None


def test_register_agent_definition(tmp_path: Path) -> None:
    """register_definition() registers an agent and uses full UUID in definition_id."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = """\
agent:
  ref: my-agent
  uuid: 12345678-abcd-ef00-0000-000000000000
  description: My Agent
"""
    definition_id = registry.register_definition(yaml_content)

    # definition_id: <type>_<ref>_<full-uuid>
    assert definition_id == "agent_my-agent_12345678-abcd-ef00-0000-000000000000"

    def_file = registry.home / "definitions" / f"{definition_id}.yaml"
    assert def_file.is_file()

    alias_data = yaml.safe_load((registry.home / "agents.yaml").read_text())
    assert alias_data["my-agent"] == definition_id


def test_register_behavior_definition(tmp_path: Path) -> None:
    """register_definition() registers a behavior and updates behaviors.yaml."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = """\
behavior:
  ref: my-behavior
  uuid: abcdefab-0000-0000-0000-000000000000
  description: My Behavior
"""
    definition_id = registry.register_definition(yaml_content)

    assert definition_id == "behavior_my-behavior_abcdefab-0000-0000-0000-000000000000"

    behaviors_data = yaml.safe_load((registry.home / "behaviors.yaml").read_text())
    agents_data = yaml.safe_load((registry.home / "agents.yaml").read_text())

    assert behaviors_data["my-behavior"] == definition_id
    assert "my-behavior" not in (agents_data or {})


def test_resolve_agent_returns_path(tmp_path: Path) -> None:
    """resolve_agent() returns the path to a registered agent's definition file."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = """\
agent:
  ref: cool-agent
  uuid: deadbeef-0000-0000-0000-000000000000
  description: Cool Agent
"""
    definition_id = registry.register_definition(yaml_content)

    result_path = registry.resolve_agent("cool-agent")

    expected_path = registry.home / "definitions" / f"{definition_id}.yaml"
    assert result_path == expected_path
    assert result_path.is_file()


def test_resolve_agent_unknown_raises(tmp_path: Path) -> None:
    """resolve_agent() raises FileNotFoundError for an unregistered agent name."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    with pytest.raises(FileNotFoundError, match="nonexistent-agent"):
        registry.resolve_agent("nonexistent-agent")


def test_register_definition_rejects_missing_fields(tmp_path: Path) -> None:
    """register_definition() raises ValueError when ref or uuid is missing."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_no_ref = """\
agent:
  uuid: 12345678-0000-0000-0000-000000000000
"""
    with pytest.raises(ValueError, match="ref"):
        registry.register_definition(yaml_no_ref)

    yaml_no_uuid = """\
behavior:
  ref: incomplete
"""
    with pytest.raises(ValueError, match="uuid"):
        registry.register_definition(yaml_no_uuid)


# ---------------------------------------------------------------------------
# Tests for unregister_definition()
# ---------------------------------------------------------------------------


def test_unregister_definition_removes_definition_file(tmp_path: Path) -> None:
    """unregister_definition() deletes the definition file."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = """\
agent:
  ref: my-agent
  uuid: 12345678-abcd-ef00-0000-000000000000
"""
    definition_id = registry.register_definition(yaml_content)

    def_file = registry.home / "definitions" / f"{definition_id}.yaml"
    assert def_file.exists()

    registry.unregister_definition("my-agent", kind="agent")
    assert not def_file.exists()


def test_unregister_definition_removes_alias_entries(tmp_path: Path) -> None:
    """unregister_definition() removes all alias entries that mapped to the definition."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = """\
agent:
  ref: my-agent
  uuid: 12345678-abcd-ef00-0000-000000000000
"""
    registry.register_definition(yaml_content)

    alias_data = yaml.safe_load((registry.home / "agents.yaml").read_text()) or {}
    assert "my-agent" in alias_data

    registry.unregister_definition("my-agent", kind="agent")

    alias_data = yaml.safe_load((registry.home / "agents.yaml").read_text()) or {}
    assert "my-agent" not in alias_data


def test_unregister_definition_removes_source_url_alias(tmp_path: Path) -> None:
    """unregister_definition() also removes the source_url alias."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = """\
agent:
  ref: url-agent
  uuid: abcdef12-0000-0000-0000-000000000000
"""
    source_url = "https://example.com/url-agent.yaml"
    registry.register_definition(yaml_content, source_url=source_url)

    alias_data = yaml.safe_load((registry.home / "agents.yaml").read_text()) or {}
    assert source_url in alias_data

    registry.unregister_definition("url-agent", kind="agent")

    alias_data = yaml.safe_load((registry.home / "agents.yaml").read_text()) or {}
    assert "url-agent" not in alias_data
    assert source_url not in alias_data


def test_unregister_definition_returns_definition_id(tmp_path: Path) -> None:
    """unregister_definition() returns the definition_id that was removed."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = """\
agent:
  ref: ret-agent
  uuid: 11111111-0000-0000-0000-000000000000
"""
    expected_id = registry.register_definition(yaml_content)
    returned_id = registry.unregister_definition("ret-agent", kind="agent")
    assert returned_id == expected_id


def test_unregister_definition_unknown_raises(tmp_path: Path) -> None:
    """unregister_definition() raises FileNotFoundError for an unknown name."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    with pytest.raises(FileNotFoundError, match="ghost-agent"):
        registry.unregister_definition("ghost-agent", kind="agent")


def test_unregister_behavior_definition(tmp_path: Path) -> None:
    """unregister_definition() works for behaviors (uses behaviors.yaml)."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    yaml_content = """\
behavior:
  ref: my-behavior
  uuid: aaaabbbb-0000-0000-0000-000000000000
"""
    definition_id = registry.register_definition(yaml_content)
    returned_id = registry.unregister_definition("my-behavior", kind="behavior")

    assert returned_id == definition_id

    alias_data = yaml.safe_load((registry.home / "behaviors.yaml").read_text()) or {}
    assert "my-behavior" not in alias_data

    def_file = registry.home / "definitions" / f"{definition_id}.yaml"
    assert not def_file.exists()


# ---------------------------------------------------------------------------
# Tests for environment helpers (unchanged)
# ---------------------------------------------------------------------------


def test_uninstall_environment_removes_directory(tmp_path: Path) -> None:
    """uninstall_environment() removes the environment directory and returns True."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    definition_id = "agent_test-agent_12345678-0000-0000-0000-000000000000"
    env_path = registry.get_environment_path(definition_id)
    env_path.mkdir(parents=True)
    assert env_path.is_dir()

    result = registry.uninstall_environment(definition_id)
    assert result is True
    assert not env_path.exists()


def test_uninstall_environment_returns_false_when_not_installed(
    tmp_path: Path,
) -> None:
    """uninstall_environment() returns False when the environment does not exist."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    result = registry.uninstall_environment("nonexistent-id")
    assert result is False
```

**Step 2: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_definition_registry.py::test_register_agent_definition -v
```
Expected: FAIL — `register_definition()` still reads `parsed.get("type")`.

**Step 3: Write minimal implementation**

In `src/amplifier_ipc/host/definition_registry.py`, replace the `register_definition()` method body (keep the signature and docstring):

```python
    def register_definition(
        self, yaml_content: str, source_url: Optional[str] = None
    ) -> str:
        """Register a definition from YAML content.

        Parses the YAML, detects the definition type from top-level key
        (agent: or behavior:), computes a definition ID, writes the definition
        to definitions/<id>.yaml, and updates the appropriate alias file.

        Args:
            yaml_content: Raw YAML string containing the definition.
            source_url: Optional URL where the definition was fetched from.

        Returns:
            The computed definition_id: '<type>_<ref>_<uuid>'.

        Raises:
            ValueError: If required fields (ref, uuid) are missing or
                        no agent:/behavior: top-level key is found.
        """
        # Self-defending: initialise home if it hasn't been set up yet.
        if not (self.home / "agents.yaml").exists():
            self.ensure_home()

        parsed = yaml.safe_load(yaml_content)
        if not isinstance(parsed, dict):
            raise ValueError("YAML content must be a mapping")

        # Detect type from top-level key
        if "agent" in parsed:
            def_type = "agent"
            inner = parsed["agent"] if isinstance(parsed["agent"], dict) else {}
        elif "behavior" in parsed:
            def_type = "behavior"
            inner = parsed["behavior"] if isinstance(parsed["behavior"], dict) else {}
        else:
            raise ValueError(
                "YAML content must have 'agent:' or 'behavior:' as a top-level key"
            )

        ref = inner.get("ref")
        uuid_value = inner.get("uuid")

        if not ref:
            raise ValueError("Definition must contain a 'ref' field")
        if not uuid_value:
            raise ValueError("Definition must contain a 'uuid' field")

        # Full UUID in definition_id (not truncated)
        definition_id = f"{def_type}_{ref}_{uuid_value}"

        # Build the data to store (copy original + optional _meta)
        stored_data = dict(parsed)
        if source_url is not None:
            content_bytes = yaml_content.encode("utf-8")
            sha256_hex = hashlib.sha256(content_bytes).hexdigest()
            stored_data["_meta"] = {
                "source_url": source_url,
                "source_hash": f"sha256:{sha256_hex}",
                "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
            }

        # Write definition file
        def_file = self.home / "definitions" / f"{definition_id}.yaml"
        def_file.write_text(yaml.dump(stored_data, default_flow_style=False))

        # Update alias file
        if def_type == "agent":
            alias_file = self.home / "agents.yaml"
        else:
            alias_file = self.home / "behaviors.yaml"

        alias_data = yaml.safe_load(alias_file.read_text()) or {}
        alias_data[ref] = definition_id
        if source_url is not None:
            alias_data[source_url] = definition_id
        alias_file.write_text(yaml.dump(alias_data, default_flow_style=False))

        return definition_id
```

**Step 4: Run all registry tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_definition_registry.py -v
```
Expected: All PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/definition_registry.py tests/host/test_definition_registry.py && git commit -m "refactor: register_definition reads nested agent:/behavior: keys, uses full UUID"
```

---

### Task 6: Update `resolve_agent()` for new format

**Files:**
- Modify: `src/amplifier_ipc/host/definitions.py:224-328`
- Test: `tests/host/test_definitions.py`

**Step 1: Write the failing tests**

Replace the existing `resolve_agent` tests in `tests/host/test_definitions.py` with:

```python
# ---------------------------------------------------------------------------
# resolve_agent tests (new format)
# ---------------------------------------------------------------------------


async def test_resolve_agent_walks_behavior_tree(tmp_path) -> None:
    """resolve_agent() correctly walks behaviors and collects services."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    # Register a behavior with a service
    behavior_yaml = """\
behavior:
  ref: my-behavior
  uuid: cccccccc-0000-0000-0000-000000000000
  tools: true
  service:
    stack: uv
    source: git+https://example.com/behavior-pkg
    command: behavior-serve
"""
    registry.register_definition(behavior_yaml)

    # Agent references the behavior by alias → ref mapping
    agent_yaml = """\
agent:
  ref: my-agent
  uuid: dddddddd-0000-0000-0000-000000000000
  orchestrator: streaming
  behaviors:
    - mybehav: my-behavior
  service:
    stack: uv
    source: git+https://example.com/agent-pkg
    command: agent-serve
"""
    registry.register_definition(agent_yaml)

    result = await resolve_agent(registry, "my-agent")

    assert isinstance(result, ResolvedAgent)
    # Agent's own service + behavior's service = 2 services
    assert len(result.services) == 2
    refs = {ref for ref, _ in result.services}
    assert "my-agent" in refs
    assert "my-behavior" in refs


async def test_resolve_agent_deduplicates_by_ref(tmp_path) -> None:
    """resolve_agent() deduplicates services by ref."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    behavior_yaml = """\
behavior:
  ref: shared
  uuid: eeeeeeee-0000-0000-0000-000000000000
  service:
    stack: uv
    source: git+https://example.com/shared
    command: shared-serve
"""
    registry.register_definition(behavior_yaml)

    agent_yaml = """\
agent:
  ref: my-agent
  uuid: ffffffff-0000-0000-0000-000000000000
  behaviors:
    - shared: shared
"""
    registry.register_definition(agent_yaml)

    result = await resolve_agent(registry, "my-agent")
    # Only the behavior's service (agent has no service block)
    assert len(result.services) == 1


async def test_resolve_agent_merges_config(tmp_path) -> None:
    """resolve_agent() merges agent config over behavior config per service."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    behavior_yaml = """\
behavior:
  ref: modes
  uuid: cccccccc-1111-0000-0000-000000000000
  tools: true
  hooks: true
  config:
    mode-tool:
      gate_policy: warn
      verbose: true
  service:
    stack: uv
    source: git+https://example.com/modes
    command: amplifier-modes-serve
"""
    registry.register_definition(behavior_yaml)

    agent_yaml = """\
agent:
  ref: my-agent
  uuid: dddddddd-1111-0000-0000-000000000000
  orchestrator: streaming
  behaviors:
    - modes: modes
  config:
    streaming:
      max_iterations: 50
    modes:mode-tool:
      gate_policy: block
"""
    registry.register_definition(agent_yaml)

    result = await resolve_agent(registry, "my-agent")

    # Agent's own service config
    assert result.service_configs["my-agent"] == {
        "streaming": {"max_iterations": 50},
    }
    # Behavior config merged — agent's gate_policy: block wins over warn,
    # but behavior's verbose: true is preserved
    modes_cfg = result.service_configs["modes"]
    assert modes_cfg["mode-tool"]["gate_policy"] == "block"
    assert modes_cfg["mode-tool"]["verbose"] is True


async def test_resolve_agent_unknown_raises(tmp_path) -> None:
    """resolve_agent() raises FileNotFoundError for an unregistered agent."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    with pytest.raises(FileNotFoundError, match="nonexistent-agent"):
        await resolve_agent(registry, "nonexistent-agent")
```

**Step 2: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_definitions.py -k "test_resolve_agent" -v
```
Expected: FAIL — `resolve_agent` uses old `svc.name` fields and `services` list.

**Step 3: Write minimal implementation**

In `src/amplifier_ipc/host/definitions.py`, update the `ResolvedAgent` dataclass:

```python
@dataclass
class ResolvedAgent:
    """Resolved agent configuration after merging behaviors into an agent definition."""

    services: list[tuple[str, ServiceEntry]] = field(default_factory=list)
    orchestrator: str | None = None
    context_manager: str | None = None
    provider: str | None = None
    component_config: dict[str, Any] = field(default_factory=dict)
    service_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
```

The `services` field is now a list of `(ref, ServiceEntry)` tuples, keyed by `ref` for deduplication.

The `service_configs` field maps service ref → merged component config for that service. This is built during resolution by merging behavior-level `config:` with agent-level `config:` (agent wins). The `<ref>:<component>` prefix syntax in agent config is resolved during merge — the prefix is stripped and the config entry is routed to the correct service's config map.

Replace the `resolve_agent()` function:

```python
async def resolve_agent(
    registry: Any,
    agent_name: str,
    extra_behaviors: list[str] | None = None,
) -> ResolvedAgent:
    """Resolve an agent by walking its behavior tree and collecting services.

    Looks up the agent definition, collects its service (if any), then
    recursively walks the behavior tree collecting and deduplicating
    services by ref.

    Args:
        registry: Registry instance used to resolve agent and behavior paths.
        agent_name: The ref alias of the agent to resolve.
        extra_behaviors: Optional additional behavior names to merge.

    Returns:
        ResolvedAgent populated with deduplicated services and agent config.

    Raises:
        FileNotFoundError: If the agent is not found in the registry.
    """
    agent_path = registry.resolve_agent(agent_name)
    agent_def = parse_agent_definition(agent_path.read_text())

    # Collect services keyed by ref for deduplication.
    services_by_ref: dict[str, ServiceEntry] = {}
    if agent_def.service is not None and agent_def.ref:
        services_by_ref[agent_def.ref] = agent_def.service

    # Collect per-service component configs.
    # Start with agent-level config — split prefixed keys (e.g., "modes:mode-tool")
    # into per-service buckets. Bare keys go to the agent's own service.
    service_configs: dict[str, dict[str, Any]] = {}
    agent_ref = agent_def.ref or ""
    for key, val in agent_def.component_config.items():
        if ":" in key:
            svc_ref, comp_name = key.split(":", 1)
            service_configs.setdefault(svc_ref, {})[comp_name] = val
        else:
            service_configs.setdefault(agent_ref, {})[key] = val

    visited_behaviors: set[str] = set()

    async def _walk_behavior(behavior_name: str) -> None:
        """Resolve a behavior, collect its service, and recurse."""
        if behavior_name in visited_behaviors:
            return
        visited_behaviors.add(behavior_name)

        try:
            behavior_path = registry.resolve_behavior(behavior_name)
        except FileNotFoundError:
            if "://" in behavior_name:
                url = behavior_name
                try:
                    yaml_content = await _fetch_url(url)
                    registry.register_definition(yaml_content, source_url=url)
                    behavior_path = registry.resolve_behavior(url)
                except (OSError, urllib.error.URLError, yaml.YAMLError, ValueError):
                    logger.warning(
                        "Failed to fetch behavior '%s' from URL; skipping.",
                        behavior_name,
                        exc_info=True,
                    )
                    return
            else:
                logger.warning(
                    "Behavior '%s' not found in local registry; skipping.",
                    behavior_name,
                )
                return

        behavior_def = parse_behavior_definition(behavior_path.read_text())

        if behavior_def.service is not None and behavior_def.ref:
            if behavior_def.ref not in services_by_ref:
                services_by_ref[behavior_def.ref] = behavior_def.service

        # Merge behavior-level config (only for keys NOT already set by agent)
        if behavior_def.component_config and behavior_def.ref:
            svc_cfg = service_configs.setdefault(behavior_def.ref, {})
            for comp_name, comp_cfg in behavior_def.component_config.items():
                if comp_name not in svc_cfg:
                    svc_cfg[comp_name] = comp_cfg
                else:
                    # Agent config wins — merge at key level within the component
                    merged = dict(comp_cfg)
                    merged.update(svc_cfg[comp_name])
                    svc_cfg[comp_name] = merged

        # Recurse into nested behaviors
        for nested in behavior_def.behaviors:
            if isinstance(nested, dict):
                for _alias, url_or_ref in nested.items():
                    await _walk_behavior(url_or_ref)
            elif isinstance(nested, str):
                await _walk_behavior(nested)

    # Walk the agent's declared behaviors
    for behavior_entry in agent_def.behaviors:
        if isinstance(behavior_entry, dict):
            for _alias, url_or_ref in behavior_entry.items():
                await _walk_behavior(url_or_ref)
        elif isinstance(behavior_entry, str):
            await _walk_behavior(behavior_entry)

    if extra_behaviors:
        for behavior_name in extra_behaviors:
            await _walk_behavior(behavior_name)

    return ResolvedAgent(
        services=[(ref, svc) for ref, svc in services_by_ref.items()],
        orchestrator=agent_def.orchestrator,
        context_manager=agent_def.context_manager,
        provider=agent_def.provider,
        component_config=agent_def.component_config,
        service_configs=service_configs,
    )
```

**Step 4: Run resolve_agent tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_definitions.py -k "test_resolve_agent" -v
```
Expected: All PASS.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/definitions.py tests/host/test_definitions.py && git commit -m "refactor: resolve_agent walks nested behavior tree, services keyed by ref"
```

---

### Task 7: Update `session_launcher.py` for new service model

**Files:**
- Modify: `src/amplifier_ipc/cli/session_launcher.py`
- Test: (inline verification — this module's tests are in e2e which we'll address later)

**Step 1: Update `build_session_config()`**

In `src/amplifier_ipc/cli/session_launcher.py`, update `build_session_config()`:

```python
def build_session_config(resolved: ResolvedAgent) -> SessionConfig:
    """Build a SessionConfig from a ResolvedAgent.

    Maps the resolved agent's service refs, orchestrator, context_manager,
    provider, and component_config to a SessionConfig suitable for the Host.
    """
    return SessionConfig(
        services=[ref for ref, _svc in resolved.services],
        orchestrator=resolved.orchestrator or "",
        context_manager=resolved.context_manager or "",
        provider=resolved.provider or "",
        component_config=resolved.component_config,
    )
```

**Step 2: Update `_build_service_overrides()`**

```python
def _build_service_overrides(
    services: list[tuple[str, ServiceEntry]],
    existing_overrides: dict[str, ServiceOverride],
) -> dict[str, ServiceOverride]:
    """Build ServiceOverride entries from definition service blocks.

    For each service with a ``command`` field, creates a ServiceOverride
    keyed by ref.  Services already covered by *existing_overrides*
    (from settings files) are left unchanged.
    """
    merged: dict[str, ServiceOverride] = dict(existing_overrides)

    for ref, svc in services:
        if ref not in merged and svc.command:
            merged[ref] = ServiceOverride(
                command=[svc.command],
                working_dir=None,
            )

    return merged
```

**Step 3: Run a quick smoke test**

```bash
cd /data/labs/amplifier-ipc && uv run python -c "from amplifier_ipc.cli.session_launcher import build_session_config, _build_service_overrides; print('import OK')"
```
Expected: `import OK`

**Step 4: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/cli/session_launcher.py && git commit -m "refactor: session_launcher uses (ref, ServiceEntry) tuples from resolved agent"
```

---

### Task 8: Update `install.py` for new service block format

**Files:**
- Modify: `src/amplifier_ipc/cli/commands/install.py:90-116`

**Step 1: Update the install command's service parsing**

In `src/amplifier_ipc/cli/commands/install.py`, update the section that reads services from the stored definition YAML (lines ~91-116). The stored definition now has `agent:` or `behavior:` as a wrapper, and `service:` is singular:

```python
    # Parse definition YAML to get the service block.
    definition: dict = yaml.safe_load(def_path.read_text()) or {}

    # Extract inner dict from agent: or behavior: wrapper
    if "agent" in definition:
        inner = definition["agent"] if isinstance(definition["agent"], dict) else {}
    elif "behavior" in definition:
        inner = definition["behavior"] if isinstance(definition["behavior"], dict) else {}
    else:
        inner = {}

    service: dict | None = inner.get("service")

    if not service or not isinstance(service, dict):
        click.echo(f"No service to install for '{name}'.")
        return

    source: str | None = service.get("source")
    if not source:
        click.echo(f"Skipping service for '{name}': no source specified.")
        return

    # Derive the definition_id from the file stem
    definition_id = def_path.stem

    install_service(registry, definition_id, source, force=force)
    command = service.get("command", name)
    click.echo(f"Installed: {command}")
```

**Step 2: Quick import smoke test**

```bash
cd /data/labs/amplifier-ipc && uv run python -c "from amplifier_ipc.cli.commands.install import install; print('import OK')"
```
Expected: `import OK`

**Step 3: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/cli/commands/install.py && git commit -m "refactor: install command reads singular service: from nested definition format"
```

---

### Task 9: Delete obsolete test files

**Files:**
- Delete: `tests/host/test_ipc_agent_definition.py`
- Delete: `tests/host/test_ipc_behavior_definitions.py`

These test files validate the old `amplifier-dev.yaml` (which uses `behavior:` wrapper with `local_ref` and plural `services:`) and the old `*-ipc.yaml` files. Both the code and the definition files they test are changing in Phase 2. They will be replaced by a new comprehensive definition-validation test suite in Phase 2.

**Step 1: Delete the files**

```bash
cd /data/labs/amplifier-ipc && rm tests/host/test_ipc_agent_definition.py tests/host/test_ipc_behavior_definitions.py
```

**Step 2: Run all remaining tests to verify nothing else broke**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/host/ tests/cli/test_commands/ -v --ignore=tests/cli/test_lifecycle.py
```
Expected: All PASS. (The `test_lifecycle.py` is ignored because it depends on definition files that haven't been rewritten yet — that's Phase 2.)

**Step 3: Commit**

```bash
cd /data/labs/amplifier-ipc && git add -A && git commit -m "chore: delete obsolete IPC definition test files (replaced in phase 2)"
```

---

### Task 10: Parser verification — run all non-lifecycle tests

**Step 1: Run the full test suite (excluding lifecycle and e2e tests that depend on definition files)**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/ -v --ignore=tests/cli/test_lifecycle.py --ignore=tests/e2e/ --ignore=tests/host/test_e2e_mock.py
```
Expected: All PASS.

**Step 2: Run linting**

```bash
cd /data/labs/amplifier-ipc && uv run ruff check src/amplifier_ipc/host/definitions.py src/amplifier_ipc/host/definition_registry.py src/amplifier_ipc/cli/commands/discover.py src/amplifier_ipc/cli/session_launcher.py src/amplifier_ipc/cli/commands/install.py
```
Expected: No errors.

**Step 3: Commit (if any formatting fixes needed)**

```bash
cd /data/labs/amplifier-ipc && git add -A && git commit -m "chore: phase 1 parser alignment complete"
```

---

### Task 11: Change `scan_package()` to return classes instead of instances

**Files:**
- Modify: `src/amplifier_ipc/protocol/discovery.py`
- Test: `tests/protocol/test_discovery.py`

Currently `scan_package()` at line 69 does `instance = obj()` — it instantiates every discovered component immediately. For the configuration protocol, we need components to be instantiated later (after `configure` arrives with their config). Change `scan_package()` to return **classes** instead of instances.

**Step 1: Write the failing test**

Add to `tests/protocol/test_discovery.py`:

```python
def test_scan_package_returns_classes_not_instances() -> None:
    """scan_package() must return component classes, not instantiated objects."""
    from amplifier_ipc.protocol.discovery import scan_package

    result = scan_package("amplifier_ipc.protocol")  # or any test package
    for component_type, items in result.items():
        for item in items:
            assert isinstance(item, type), (
                f"Expected a class, got instance of {type(item).__name__} "
                f"for component_type={component_type}"
            )
```

**Step 2: Run test to verify it fails**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/protocol/test_discovery.py::test_scan_package_returns_classes_not_instances -v
```
Expected: FAIL — `scan_package` currently returns instances.

**Step 3: Write minimal implementation**

In `src/amplifier_ipc/protocol/discovery.py`, change the line that does `instance = obj()` to just collect the class:

```python
# Before (line ~69):
instance = obj()
# ... append instance to result dict

# After:
# Don't instantiate — return the class itself for lazy instantiation
# ... append obj (the class) to result dict
```

The return type changes from `dict[str, list[Any]]` (instances) to `dict[str, list[type]]` (classes).

**Step 4: Run test to verify it passes**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/protocol/test_discovery.py -v
```
Expected: PASS. Note: other tests that relied on `scan_package` returning instances may break — fix them to work with classes.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/protocol/discovery.py tests/protocol/test_discovery.py && git commit -m "refactor: scan_package returns classes instead of instances for lazy instantiation"
```

---

### Task 12: Update `Server` for lazy instantiation and `configure` method

**Files:**
- Modify: `src/amplifier_ipc/protocol/server.py`
- Test: `tests/protocol/test_server.py`

The `Server` must store classes from `scan_package()` instead of instances, support a `configure` method that instantiates components with config, and have `describe` work from class metadata.

**Step 1: Write the failing tests**

Add to `tests/protocol/test_server.py`:

```python
def test_server_describe_before_configure() -> None:
    """describe must work before configure — uses class metadata, not instances."""
    # Create a Server, call describe, verify it returns capabilities
    # without configure having been called.
    pass  # Implement with actual Server + test package


def test_server_configure_instantiates_with_config() -> None:
    """configure must instantiate component classes with their config."""
    # Create a Server, send configure with component configs,
    # verify components are now instances with config applied.
    pass  # Implement with actual Server + test package


def test_server_configure_no_config_instantiates_without_args() -> None:
    """configure with empty config must instantiate components with no args."""
    # Components not in the config map get cls() — no config arg.
    pass  # Implement with actual Server + test package
```

**Step 2: Write implementation**

In `src/amplifier_ipc/protocol/server.py`:

1. **`__init__`** stores classes from `scan_package()` instead of instances:

```python
def __init__(self, package_name: str) -> None:
    discovered = scan_package(package_name)
    # Store classes — not yet instantiated
    self._tool_classes: list[type] = discovered.get("tools", [])
    self._hook_classes: list[type] = discovered.get("hooks", [])
    # ... other component types
    self._instances_ready = False
    self._tool_instances: list = []
    self._hook_instances: list = []
```

2. **`describe`** must work from class metadata. The decorators set `__amplifier_component__`, tool `name`, `__amplifier_hook_events__`, etc. on the class itself — verify these are accessible without instantiation:

```python
def _describe_tools(self) -> list[dict]:
    """Build tool descriptions from class metadata."""
    tools = []
    for cls in self._tool_classes:
        name = getattr(cls, "name", cls.__name__)
        # ... read schema, description from class attributes
        tools.append({"name": name, ...})
    return tools
```

3. **Add `configure` method handler**:

```python
async def handle_configure(self, params: dict) -> dict:
    """Instantiate components with their config.

    Args:
        params: {"config": {"component_name": {"key": "val", ...}, ...}}

    Returns:
        {"status": "ok"}
    """
    config_map = params.get("config", {})

    for cls in self._tool_classes:
        comp_name = getattr(cls, "name", cls.__name__)
        comp_config = config_map.get(comp_name)
        if comp_config is not None:
            instance = cls(config=comp_config)
        else:
            instance = cls()
        self._tool_instances.append(instance)

    for cls in self._hook_classes:
        comp_name = getattr(cls, "name", cls.__name__)
        comp_config = config_map.get(comp_name)
        if comp_config is not None:
            instance = cls(config=comp_config)
        else:
            instance = cls()
        self._hook_instances.append(instance)

    # ... other component types

    self._instances_ready = True
    return {"status": "ok"}
```

4. **Auto-instantiate on first request if `configure` is never called** (for content-only services or backward compat):

```python
def _ensure_instances(self) -> None:
    """Auto-instantiate components with no config if configure was never called."""
    if not self._instances_ready:
        for cls in self._tool_classes:
            self._tool_instances.append(cls())
        for cls in self._hook_classes:
            self._hook_instances.append(cls())
        self._instances_ready = True
```

**Step 3: Run tests**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/protocol/test_server.py -v
```
Expected: All PASS.

**Step 4: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/protocol/server.py tests/protocol/test_server.py && git commit -m "feat: Server supports configure method for lazy component instantiation with config"
```

---

### Task 13: Verify decorators set metadata on classes (not just instances)

**Files:**
- Verify: `src/amplifier_ipc/protocol/decorators.py`
- Test: `tests/protocol/test_decorators.py`

The decorators (`@tool`, `@hook`, etc.) must set metadata attributes (`__amplifier_component__`, `name`, `__amplifier_hook_events__`, `__amplifier_hook_priority__`, etc.) on the **class** itself, not just on instances. This is required because `describe` now reads metadata from classes before they're instantiated.

**Step 1: Write the verification test**

```python
def test_tool_decorator_sets_class_metadata() -> None:
    """@tool decorator must set metadata accessible on the class (not just instances)."""
    from amplifier_ipc.protocol.decorators import tool

    @tool
    class MyTestTool:
        name = "test-tool"

    # These must be accessible on the CLASS, not an instance
    assert hasattr(MyTestTool, "__amplifier_component__")
    assert MyTestTool.__amplifier_component__ == "tool"


def test_hook_decorator_sets_class_metadata() -> None:
    """@hook decorator must set event list and priority on the class."""
    from amplifier_ipc.protocol.decorators import hook

    @hook(events=["before_call"], priority=10)
    class MyTestHook:
        name = "test-hook"

    assert hasattr(MyTestHook, "__amplifier_hook_events__")
    assert MyTestHook.__amplifier_hook_events__ == ["before_call"]
    assert MyTestHook.__amplifier_hook_priority__ == 10
```

**Step 2: Run tests**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/protocol/test_decorators.py -v
```
Expected: PASS — decorators already set attributes on the class (they modify `cls` directly). If any fail, update the decorators to use `cls.__attribute__ = value` instead of setting on instances.

**Step 3: Commit (if changes needed)**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/protocol/decorators.py tests/protocol/test_decorators.py && git commit -m "test: verify decorators set metadata on classes for pre-instantiation describe"
```

---

### Task 14: Host sends `configure` after `describe`

**Files:**
- Modify: `src/amplifier_ipc/host/host.py`
- Test: `tests/host/test_host.py`

After the host calls `describe` on each service, it must send a `configure` call with the merged config for that service's components (from `ResolvedAgent.service_configs`).

**Step 1: Write the failing test**

```python
async def test_host_sends_configure_after_describe() -> None:
    """Host must send configure with merged config after describe."""
    # Use a mock service that records method calls.
    # After _build_registry(), verify that 'configure' was called
    # on each service with the expected config dict.
    pass  # Implement with mock service transport
```

**Step 2: Write implementation**

In `src/amplifier_ipc/host/host.py`, after `_build_registry()` calls `describe` on each service, add the `configure` call:

```python
async def _build_registry(self) -> None:
    """Discover capabilities from all services."""
    for ref, transport in self._transports.items():
        # Existing: describe
        desc = await transport.request("describe", {})
        self._register_capabilities(ref, desc)

        # NEW: send configure with merged config for this service
        service_config = self._service_configs.get(ref, {})
        if service_config:
            await transport.request("configure", {"config": service_config})
```

The `_service_configs` dict comes from `ResolvedAgent.service_configs`, passed to the `Host` during initialization or session setup.

**Step 3: Run tests**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_host.py -v
```
Expected: All PASS.

**Step 4: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/host.py tests/host/test_host.py && git commit -m "feat: host sends configure with merged component config after describe"
```

---

### Task 15: Final verification — full Phase 1

**Step 1: Run the full test suite (excluding lifecycle and e2e tests that depend on definition files)**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/ -v --ignore=tests/cli/test_lifecycle.py --ignore=tests/e2e/ --ignore=tests/host/test_e2e_mock.py
```
Expected: All PASS.

**Step 2: Run linting on all modified files**

```bash
cd /data/labs/amplifier-ipc && uv run ruff check src/amplifier_ipc/host/definitions.py src/amplifier_ipc/host/definition_registry.py src/amplifier_ipc/cli/commands/discover.py src/amplifier_ipc/cli/session_launcher.py src/amplifier_ipc/cli/commands/install.py src/amplifier_ipc/protocol/discovery.py src/amplifier_ipc/protocol/server.py src/amplifier_ipc/protocol/decorators.py src/amplifier_ipc/host/host.py
```
Expected: No errors.

**Step 3: Commit**

```bash
cd /data/labs/amplifier-ipc && git add -A && git commit -m "chore: phase 1 parser alignment and configuration protocol complete"
```

---

## Summary of Phase 1 Changes

### Parser alignment (Tasks 1–10)

| File | Change |
|------|--------|
| `src/amplifier_ipc/host/definitions.py` | `ServiceEntry`: `name`/`installer` → `stack`/`source`/`command`. `AgentDefinition`/`BehaviorDefinition`: `local_ref` → `ref`, removed `type`, `services` → singular `service`, bools for capabilities, added `component_config`. Deleted `_to_str_list`, `_to_dict`, `_parse_services`. Added `_parse_service`. Rewrote both parsers (including `config:` parsing) and `resolve_agent` (with config merging into `service_configs`). |
| `src/amplifier_ipc/host/definition_registry.py` | `register_definition`: detects `agent:`/`behavior:` top-level key, reads `ref`/`uuid` from inner dict, full UUID in `definition_id`. |
| `src/amplifier_ipc/cli/commands/discover.py` | `_try_parse_definition`: checks for `agent`/`behavior` in parsed dict instead of `type:`. Uses `ref` not `local_ref`. |
| `src/amplifier_ipc/cli/session_launcher.py` | `build_session_config` and `_build_service_overrides` use `(ref, ServiceEntry)` tuples. |
| `src/amplifier_ipc/cli/commands/install.py` | Reads singular `service:` from nested wrapper. |
| `tests/host/test_definitions.py` | All tests rewritten for new format, including config parsing and config merging tests. |
| `tests/host/test_definition_registry.py` | All tests rewritten for new format. |
| `tests/cli/test_commands/test_discover.py` | Fixtures and assertions updated for new format. |
| `tests/host/test_ipc_agent_definition.py` | **DELETED** (replaced in Phase 2). |
| `tests/host/test_ipc_behavior_definitions.py` | **DELETED** (replaced in Phase 2). |

### Configuration protocol (Tasks 11–15)

| File | Change |
|------|--------|
| `src/amplifier_ipc/protocol/discovery.py` | `scan_package()` returns classes instead of instances for lazy instantiation. |
| `src/amplifier_ipc/protocol/server.py` | `Server.__init__` stores classes. `describe` works from class metadata. Added `handle_configure` method that instantiates components with config. Auto-instantiates on first request if `configure` is never called. |
| `src/amplifier_ipc/protocol/decorators.py` | Verified: decorators set metadata on classes (accessible before instantiation). |
| `src/amplifier_ipc/host/host.py` | `_build_registry()` sends `configure` call after `describe`, passing merged `service_configs` for each service. |
| `tests/protocol/test_discovery.py` | Test that `scan_package` returns classes. |
| `tests/protocol/test_server.py` | Tests for `describe` before `configure`, `configure` with config, and `configure` with empty config. |
| `tests/protocol/test_decorators.py` | Tests that decorator metadata is accessible on classes. |
| `tests/host/test_host.py` | Test that host sends `configure` after `describe`. |