"""
Validation tests for the rewritten default (foundation) agent definition.
The file must have: agent: top-level key with ref 'foundation', uuid, orchestrator,
provider, context_manager, 24 behaviors as {alias: url} single-key dicts,
and a service block with stack/source/command.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
AGENT_FILE = (
    PROJECT_ROOT / "services" / "amplifier-foundation" / "agents" / "default.yaml"
)

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

EXPECTED_UUID = "3898a638-71de-427a-8183-b80eba8b26be"
EXPECTED_REF = "foundation"
EXPECTED_ORCHESTRATOR = "streaming"
EXPECTED_CONTEXT_MANAGER = "simple"
EXPECTED_PROVIDER = "providers:anthropic"
EXPECTED_SERVICE_COMMAND = "amplifier-foundation-serve"
EXPECTED_SERVICE_STACK = "uv"
EXPECTED_BEHAVIOR_COUNT = 24

RAW_BASE = "https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/"

# All 24 expected behaviors: alias -> URL suffix
EXPECTED_BEHAVIORS = {
    "agents": "amplifier-foundation/behaviors/agents.yaml",
    "amplifier-dev-behavior": "amplifier-foundation/behaviors/amplifier-dev.yaml",
    "foundation-expert": "amplifier-foundation/behaviors/foundation-expert.yaml",
    "logging": "amplifier-foundation/behaviors/logging.yaml",
    "progress-monitor": "amplifier-foundation/behaviors/progress-monitor.yaml",
    "redaction": "amplifier-foundation/behaviors/redaction.yaml",
    "sessions": "amplifier-foundation/behaviors/sessions.yaml",
    "shadow-amplifier": "amplifier-foundation/behaviors/shadow-amplifier.yaml",
    "status-context": "amplifier-foundation/behaviors/status-context.yaml",
    "streaming-ui": "amplifier-foundation/behaviors/streaming-ui.yaml",
    "tasks": "amplifier-foundation/behaviors/tasks.yaml",
    "todo-reminder": "amplifier-foundation/behaviors/todo-reminder.yaml",
    "modes": "amplifier-modes/behaviors/modes.yaml",
    "skills": "amplifier-skills/behaviors/skills.yaml",
    "skills-tool": "amplifier-skills/behaviors/skills-tool.yaml",
    "routing": "amplifier-routing-matrix/behaviors/routing.yaml",
    "recipes": "amplifier-recipes/behaviors/recipes.yaml",
    "apply-patch": "amplifier-filesystem/behaviors/apply-patch.yaml",
    "superpowers-methodology": "amplifier-superpowers/behaviors/superpowers-methodology.yaml",
    "amplifier-expert": "amplifier-amplifier/behaviors/amplifier-expert.yaml",
    "amplifier-dev-hygiene": "amplifier-amplifier/behaviors/amplifier-dev.yaml",
    "core-expert": "amplifier-core/behaviors/core-expert.yaml",
    "design-intelligence": "amplifier-design-intelligence/behaviors/design-intelligence.yaml",
    "browser-tester": "amplifier-browser-tester/behaviors/browser-tester.yaml",
}


def load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def test_default_agent_top_level_key() -> None:
    """default.yaml must have top-level 'agent' key."""
    data = load_yaml(AGENT_FILE)
    assert "agent" in data, (
        f"Missing top-level 'agent' key; got keys: {list(data.keys())}"
    )


def test_default_agent_ref() -> None:
    """agent.ref must be 'foundation'."""
    data = load_yaml(AGENT_FILE)
    inner = data["agent"]
    assert inner.get("ref") == EXPECTED_REF, (
        f"ref mismatch: expected '{EXPECTED_REF}', got '{inner.get('ref')}'"
    )


def test_default_agent_uuid() -> None:
    """agent.uuid must be the correct value and valid UUID format."""
    data = load_yaml(AGENT_FILE)
    inner = data["agent"]
    uuid_val = str(inner.get("uuid", ""))
    assert uuid_val == EXPECTED_UUID, (
        f"uuid mismatch: expected '{EXPECTED_UUID}', got '{uuid_val}'"
    )
    assert UUID_RE.match(uuid_val), f"uuid is not valid UUID format: '{uuid_val}'"


def test_default_agent_orchestrator() -> None:
    """agent.orchestrator must be 'streaming'."""
    data = load_yaml(AGENT_FILE)
    inner = data["agent"]
    assert inner.get("orchestrator") == EXPECTED_ORCHESTRATOR, (
        f"orchestrator mismatch: expected '{EXPECTED_ORCHESTRATOR}', "
        f"got '{inner.get('orchestrator')}'"
    )


def test_default_agent_context_manager() -> None:
    """agent.context_manager must be 'simple'."""
    data = load_yaml(AGENT_FILE)
    inner = data["agent"]
    assert inner.get("context_manager") == EXPECTED_CONTEXT_MANAGER, (
        f"context_manager mismatch: expected '{EXPECTED_CONTEXT_MANAGER}', "
        f"got '{inner.get('context_manager')}'"
    )


def test_default_agent_provider() -> None:
    """agent.provider must be 'providers:anthropic'."""
    data = load_yaml(AGENT_FILE)
    inner = data["agent"]
    assert inner.get("provider") == EXPECTED_PROVIDER, (
        f"provider mismatch: expected '{EXPECTED_PROVIDER}', "
        f"got '{inner.get('provider')}'"
    )


def test_default_agent_behavior_count() -> None:
    """agent.behaviors must have exactly 24 entries."""
    data = load_yaml(AGENT_FILE)
    inner = data["agent"]
    behaviors = inner.get("behaviors", [])
    assert len(behaviors) == EXPECTED_BEHAVIOR_COUNT, (
        f"behaviors count mismatch: expected {EXPECTED_BEHAVIOR_COUNT}, "
        f"got {len(behaviors)}"
    )


def test_default_agent_behaviors_are_single_key_dicts() -> None:
    """Each behavior entry must be a single-key dict {alias: url}."""
    data = load_yaml(AGENT_FILE)
    inner = data["agent"]
    behaviors = inner.get("behaviors", [])
    errors = []
    for i, b in enumerate(behaviors):
        if not isinstance(b, dict):
            errors.append(f"behaviors[{i}] is not a dict: {b!r}")
        elif len(b) != 1:
            errors.append(
                f"behaviors[{i}] is not a single-key dict (has {len(b)} keys): {b!r}"
            )
    assert not errors, "Behavior format errors:\n" + "\n".join(errors)


def test_default_agent_behavior_urls_are_raw_github() -> None:
    """Each behavior URL must use canonical raw GitHub format with .yaml extension."""
    data = load_yaml(AGENT_FILE)
    inner = data["agent"]
    behaviors = inner.get("behaviors", [])
    errors = []
    for b in behaviors:
        if not isinstance(b, dict) or len(b) != 1:
            continue
        alias, url = next(iter(b.items()))
        if not url.startswith(RAW_BASE):
            errors.append(
                f"behavior '{alias}' URL does not start with '{RAW_BASE}': {url!r}"
            )
        if not url.endswith(".yaml"):
            errors.append(f"behavior '{alias}' URL does not end with '.yaml': {url!r}")
    assert not errors, "Behavior URL format errors:\n" + "\n".join(errors)


def test_default_agent_all_expected_behaviors_present() -> None:
    """All 24 expected behaviors must be present with correct aliases and URLs."""
    data = load_yaml(AGENT_FILE)
    inner = data["agent"]
    behaviors = inner.get("behaviors", [])

    # Build alias -> url map from file
    actual: dict[str, str] = {}
    for b in behaviors:
        if isinstance(b, dict) and len(b) == 1:
            alias, url = next(iter(b.items()))
            actual[alias] = url

    errors = []
    for alias, suffix in EXPECTED_BEHAVIORS.items():
        expected_url = RAW_BASE + suffix
        if alias not in actual:
            errors.append(f"Missing behavior alias '{alias}'")
        elif actual[alias] != expected_url:
            errors.append(
                f"behavior '{alias}' URL mismatch:\n"
                f"  expected: {expected_url}\n"
                f"  got:      {actual[alias]}"
            )

    assert not errors, "Behavior content errors:\n" + "\n".join(errors)


def test_default_agent_service_block() -> None:
    """agent.service must have stack='uv' and command='amplifier-foundation-serve'."""
    data = load_yaml(AGENT_FILE)
    inner = data["agent"]
    assert "service" in inner, "Missing 'service' block in agent definition"
    svc = inner["service"]
    assert svc.get("stack") == EXPECTED_SERVICE_STACK, (
        f"service.stack mismatch: expected '{EXPECTED_SERVICE_STACK}', "
        f"got '{svc.get('stack')}'"
    )
    assert svc.get("command") == EXPECTED_SERVICE_COMMAND, (
        f"service.command mismatch: expected '{EXPECTED_SERVICE_COMMAND}', "
        f"got '{svc.get('command')}'"
    )


def test_default_agent_boolean_flags() -> None:
    """agent must have tools, hooks, agents, context all set to true."""
    data = load_yaml(AGENT_FILE)
    inner = data["agent"]
    for flag in ("tools", "hooks", "agents", "context"):
        assert inner.get(flag) is True, (
            f"Flag '{flag}' must be true, got {inner.get(flag)!r}"
        )
